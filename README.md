# Web Load Testing Tool

A simple yet powerful tool for load testing web servers using Python. 

## Features
- Configurable number of requests and test duration
- Multithreading support
- Response time statistics (min/max/avg/median/percentiles)
- Warmup phase option
- Progress bar during testing
- Export results to JSON/CSV
- Error tracking and classification

## Installation
```bash
pip install requests tqdm
```

## Usage
### Basic usage:
```bash
python stresstest.py http://example.com
```

### Advanced options:
```bash
python stresstest.py http://example.com -n 1000 -t 20 -w 5 --output json
```

## Parameters
`-n, --num_requests`: Total number of requests to make
`-d, --duration`: Test duration in seconds
`-t, --threads`: Number of concurrent threads (default: 10)
`-w, --warmup`: Warmup duration in seconds
`--timeout`: Request timeout in seconds (default: 30)
`--output`: Save results in 'json' or 'csv' format
`--output-file`: Custom filename for results

## Example Output
```
Results:
Total requests: 1000
Successful requests: 985
Success rate: 98.50%
Requests per second: 95.23

Response time (seconds):
Minimum: 0.102
Maximum: 0.856
Average: 0.245
Median: 0.215
95th percentile: 0.412
99th percentile: 0.633
```
