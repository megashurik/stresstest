import aiohttp
import asyncio
import time
import argparse
from tqdm import tqdm
import statistics
import json
import csv
from collections import defaultdict
import sys

VERSION = "1.0.3"

class RequestStats:
    def __init__(self):
        self.response_times = []
        self.errors = defaultdict(int)
        self.successful_requests = 0
        self.total_requests = 0
        self.start_time = None
        self.end_time = None

    def add_response(self, response_time, is_success, error_type=None):
        if is_success:
            self.successful_requests += 1
            self.response_times.append(response_time)
        else:
            self.errors[error_type] += 1
        self.total_requests += 1

    def get_percentile(self, p):
        if not self.response_times:
            return 0
        return statistics.quantiles(self.response_times, n=100)[p-1]

    def get_stats(self):
        duration = self.end_time - self.start_time
        
        if not self.response_times:
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "error_count": sum(self.errors.values()),
                "errors": dict(self.errors),
                "requests_per_second": self.total_requests / duration,
                "success_rate": 0.0,
                "total_duration": duration
            }

        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "requests_per_second": self.total_requests / duration,
            "success_rate": (self.successful_requests / self.total_requests) * 100,
            "min_response_time": min(self.response_times),
            "max_response_time": max(self.response_times),
            "avg_response_time": statistics.mean(self.response_times),
            "median_response_time": statistics.median(self.response_times),
            "p95_response_time": self.get_percentile(95),
            "p99_response_time": self.get_percentile(99),
            "error_count": sum(self.errors.values()),
            "errors": dict(self.errors),
            "total_duration": duration
        }

async def make_request(session, url, timeout, headers):
    try:
        start_time = time.time()
        async with session.get(url, timeout=timeout, headers=headers) as response:
            response_time = time.time() - start_time
            if response.status == 200:
                return True, response_time, None
            else:
                return False, None, f"HTTP_{response.status}"
    except asyncio.TimeoutError:
        return False, None, "timeout"
    except aiohttp.ClientError as e:
        return False, None, str(type(e).__name__)

async def warmup(url, target_concurrency, warmup_duration, timeout, headers):
    print("\nWarming up the system...")
    current_concurrency = 1
    start_time = time.time()
    
    while current_concurrency <= target_concurrency:
        if time.time() - start_time >= warmup_duration:
            break
            
        connector = aiohttp.TCPConnector(limit=0)  # Remove connection limits
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [make_request(session, url, timeout, headers) for _ in range(current_concurrency)]
            await asyncio.gather(*tasks)
        
        print(f"Warmup: {current_concurrency} concurrent requests")
        current_concurrency *= 2
        if current_concurrency > target_concurrency:
            current_concurrency = target_concurrency

async def test_load(url, num_requests, duration, concurrency, timeout, warmup_time, headers):
    stats = RequestStats()
    stop_event = asyncio.Event()
    semaphore = asyncio.Semaphore(concurrency)  # Ограничиваем количество одновременных запросов
    request_counter = 0  # Счётчик запросов
    request_counter_lock = asyncio.Lock()  # Блокировка для атомарного увеличения счётчика

    if warmup_time:
        await warmup(url, concurrency, warmup_time, timeout, headers)

    async def worker(url, pbar):
        nonlocal request_counter
        while not stop_event.is_set():
            async with request_counter_lock:
                if num_requests and request_counter >= num_requests:
                    stop_event.set()
                    break
                request_counter += 1
            
            async with semaphore:  # Ограничиваем количество одновременных запросов
                connector = aiohttp.TCPConnector(limit=0)  # Remove connection limits
                async with aiohttp.ClientSession(connector=connector) as session:
                    success, response_time, error_type = await make_request(session, url, timeout, headers)
                    stats.add_response(response_time, success, error_type)
                    pbar.update(1)

    print("\nStarting the test...")
    stats.start_time = time.time()

    with tqdm(total=num_requests if num_requests else None, unit="req") as pbar:
        tasks = [asyncio.create_task(worker(url, pbar)) for _ in range(concurrency)]
        
        if duration:
            await asyncio.sleep(duration)
            stop_event.set()
        
        await asyncio.gather(*tasks)

    stats.end_time = time.time()
    return stats

def save_results(stats, output_format, filename):
    results = stats.get_stats()
    
    if output_format == 'json':
        with open(filename, 'w') as f:
            json.dump(results, f, indent=4)
    elif output_format == 'csv':
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            for key, value in results.items():
                writer.writerow([key, value])

async def main():
    parser = argparse.ArgumentParser(description=f'Web performance testing tool v{VERSION}')
    parser.add_argument('url', help='URL to test')
    parser.add_argument('-n', '--num_requests', type=int, help='Number of requests')
    parser.add_argument('-d', '--duration', type=float, help='Test duration in seconds')
    parser.add_argument('-t', '--threads', type=int, default=10,
                        help='Number of concurrent requests (default: 10)')
    parser.add_argument('--timeout', type=float, default=30,
                        help='Request timeout in seconds (default: 30)')
    parser.add_argument('-w', '--warmup', type=float,
                        help='Warmup time in seconds')
    parser.add_argument('--output', choices=['json', 'csv'],
                        help='Output format for results')
    parser.add_argument('--output-file', help='File to save results')
    parser.add_argument('--header', action='append', help='Add custom header (format: "Key: Value")')
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    if not args.num_requests and not args.duration:
        args.duration = 10.0

    if args.output and not args.output_file:
        args.output_file = f'results.{args.output}'

    headers = {'User-Agent': f'Stresstest/{VERSION}'}
    if args.header:
        for header in args.header:
            key, value = header.split(':', 1)
            headers[key.strip()] = value.strip()

    stats = await test_load(
        args.url,
        args.num_requests,
        args.duration,
        args.threads,
        args.timeout,
        args.warmup,
        headers
    )

    results = stats.get_stats()
    
    print("\nTest results:")
    print(f"URL: {args.url}")
    print(f"Total requests: {results['total_requests']}")
    print(f"Successful requests: {results['successful_requests']}")
    print(f"Success rate: {results['success_rate']:.2f}%")
    print(f"Requests per second: {results['requests_per_second']:.2f}")
    
    if args.num_requests:
        print(f"Total time to complete {args.num_requests} requests: {results['total_duration']:.2f} seconds")
    
    if results['successful_requests'] > 0:
        print("\nResponse time (seconds):")
        print(f"Min: {results['min_response_time']:.3f}")
        print(f"Max: {results['max_response_time']:.3f}")
        print(f"Avg: {results['avg_response_time']:.3f}")
        print(f"Median: {results['median_response_time']:.3f}")
        print(f"95th percentile: {results['p95_response_time']:.3f}")
        print(f"99th percentile: {results['p99_response_time']:.3f}")
    
    if results['errors']:
        print("\nErrors:")
        for error_type, count in results['errors'].items():
            print(f"{error_type}: {count}")

    if args.output:
        save_results(stats, args.output, args.output_file)
        print(f"\nResults saved to {args.output_file}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(0)
