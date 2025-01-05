import requests
import time
import argparse
from concurrent.futures import ThreadPoolExecutor
import threading
import statistics
import json
import csv
from collections import defaultdict
from tqdm import tqdm
import sys

VERSION = "1.0.2"

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
                "success_rate": 0.0,  # добавляем эти поля даже если нет успешных запросов
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


def make_request(url, timeout, stop_event):
    if stop_event.is_set():
        return None, None, None

    headers = {
        'User-Agent': f'Stresstest/{VERSION}'
    }

    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout, headers=headers)
        response_time = time.time() - start_time
        return response.status_code == 200, response_time, None
    except requests.Timeout:
        return False, None, "timeout"
    except requests.ConnectionError:
        return False, None, "connection_error"
    except Exception as e:
        return False, None, str(type(e).__name__)

def warmup(url, target_threads, warmup_duration, timeout):
    print("\nРазогрев системы...")
    current_threads = 1
    start_time = time.time()
    
    while current_threads <= target_threads:
        if time.time() - start_time >= warmup_duration:
            break
            
        with ThreadPoolExecutor(max_workers=current_threads) as executor:
            for _ in range(current_threads):
                executor.submit(make_request, url, timeout, threading.Event())
        print(f"Разогрев: {current_threads} потоков")
        current_threads *= 2
        if current_threads > target_threads:
            current_threads = target_threads

def test_load(url, num_requests, duration, num_threads, timeout, warmup_time):
    stats = RequestStats()
    stop_event = threading.Event()
    
    if warmup_time:
        warmup(url, num_threads, warmup_time, timeout)

    def worker(url, pbar):
        while not stop_event.is_set():
            if num_requests and stats.total_requests >= num_requests:
                stop_event.set()
                break
            
            success, response_time, error_type = make_request(url, timeout, stop_event)
            stats.add_response(response_time, success, error_type)
            pbar.update(1)

    print("\nЗапуск тестирования...")
    stats.start_time = time.time()
    
    with tqdm(total=num_requests if num_requests else None, unit="req") as pbar:
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, url, pbar) for _ in range(num_threads)]
            
            if duration:
                time.sleep(duration)
                stop_event.set()
            
            for future in futures:
                future.result()

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
            writer.writerow(['Метрика', 'Значение'])
            for key, value in results.items():
                writer.writerow([key, value])

def main():
    parser = argparse.ArgumentParser(description=f'Тест производительности веб-ресурса v{VERSION}')
    parser.add_argument('url', help='URL для тестирования')
    parser.add_argument('-n', '--num_requests', type=int, help='Количество запросов')
    parser.add_argument('-d', '--duration', type=float, help='Длительность теста в секундах')
    parser.add_argument('-t', '--threads', type=int, default=10,
                        help='Количество потоков (по умолчанию: 10)')
    parser.add_argument('--timeout', type=float, default=30,
                        help='Timeout для запросов в секундах (по умолчанию: 30)')
    parser.add_argument('-w', '--warmup', type=float,
                        help='Время разогрева в секундах')
    parser.add_argument('--output', choices=['json', 'csv'],
                        help='Формат вывода результатов')
    parser.add_argument('--output-file', help='Файл для сохранения результатов')
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    if not args.num_requests and not args.duration:
        args.duration = 10.0

    if args.output and not args.output_file:
        args.output_file = f'results.{args.output}'

    stats = test_load(
        args.url,
        args.num_requests,
        args.duration,
        args.threads,
        args.timeout,
        args.warmup
    )

    results = stats.get_stats()
    
    print("\nРезультаты тестирования:")
    print(f"URL: {args.url}")
    print(f"Всего запросов: {results['total_requests']}")
    print(f"Успешных запросов: {results['successful_requests']}")
    print(f"Процент успешных: {results['success_rate']:.2f}%")
    print(f"Запросов в секунду: {results['requests_per_second']:.2f}")
    
    if results['successful_requests'] > 0:
        print("\nВремя ответа (секунды):")
        print(f"Минимальное: {results['min_response_time']:.3f}")
        print(f"Максимальное: {results['max_response_time']:.3f}")
        print(f"Среднее: {results['avg_response_time']:.3f}")
        print(f"Медиана: {results['median_response_time']:.3f}")
        print(f"95-й процентиль: {results['p95_response_time']:.3f}")
        print(f"99-й процентиль: {results['p99_response_time']:.3f}")
    
    if results['errors']:
        print("\nОшибки:")
        for error_type, count in results['errors'].items():
            print(f"{error_type}: {count}")

    if args.output:
        save_results(stats, args.output, args.output_file)
        print(f"\nРезультаты сохранены в {args.output_file}")

if __name__ == '__main__':
    main()
