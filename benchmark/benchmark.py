#!/usr/bin/env python3
"""
TAK Server Benchmarking Tool

Sends a configurable number of CoT messages to a TAK server to measure
throughput and performance.

Usage:
    python benchmark.py --count 1000 --rate 100
    python benchmark.py --count 5000 --rate 0  # No rate limit (max speed)
    python benchmark.py --duration 60 --rate 50  # Send for 60 seconds at 50 msg/s

Environment Variables:
    COT_URL - TAK server URL (default: tls://localhost:8089)
    PYTAK_TLS_CLIENT_CERT - Path to client certificate
    PYTAK_TLS_CLIENT_PASSWORD - Certificate password
"""

import asyncio
import argparse
import os
import sys
import time
import logging
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from dataclasses import dataclass
from typing import Optional

import pytak

# Set up logging
Logger = logging.getLogger(__name__)


@dataclass
class BenchmarkStats:
    """Statistics from a benchmark run."""
    total_sent: int = 0
    total_errors: int = 0
    start_time: float = 0
    end_time: float = 0
    min_latency_ms: float = float('inf')
    max_latency_ms: float = 0
    total_latency_ms: float = 0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def messages_per_second(self) -> float:
        if self.duration > 0:
            return self.total_sent / self.duration
        return 0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_sent > 0:
            return self.total_latency_ms / self.total_sent
        return 0

    def report(self) -> str:
        lines = [
            "",
            "=" * 60,
            "BENCHMARK RESULTS",
            "=" * 60,
            f"Total Messages Sent:    {self.total_sent:,}",
            f"Total Errors:           {self.total_errors:,}",
            f"Duration:               {self.duration:.2f} seconds",
            f"Throughput:             {self.messages_per_second:.2f} messages/second",
            "",
            "Latency (queue time):",
            f"  Min:                  {self.min_latency_ms:.2f} ms",
            f"  Max:                  {self.max_latency_ms:.2f} ms",
            f"  Avg:                  {self.avg_latency_ms:.2f} ms",
            "=" * 60,
        ]
        return "\n".join(lines)


class BenchmarkSerializer(pytak.QueueWorker):
    """
    Benchmark worker that sends CoT messages at a configurable rate.
    """

    def __init__(self, queue, config, count: int, rate: float, duration: Optional[float] = None, unique_tracks: int = 10):
        super().__init__(queue, config)
        self.config = config
        self.target_count = count
        self.rate = rate  # messages per second, 0 = unlimited
        self.duration = duration  # optional duration limit in seconds
        self.unique_tracks = unique_tracks  # 0 = all unique, >0 = cycle through N tracks
        self.stats = BenchmarkStats()
        self.base_lat = float(config.get("BASE_LAT", "40.7128"))
        self.base_lon = float(config.get("BASE_LON", "-74.0060"))

    def generate_cot_event(self, index: int) -> bytes:
        """Generate a CoT event for benchmarking using pytak.gen_cot_xml."""
        # Create unique position for each message (spread around base point)
        lat = self.base_lat + (index % 100) * 0.001
        lon = self.base_lon + (index // 100) * 0.001

        # Generate track ID based on unique_tracks setting
        if self.unique_tracks > 0:
            track_id = index % self.unique_tracks
        else:
            track_id = index  # All unique

        uid = f"BENCH-{track_id:06d}"
        callsign = f"BENCH{track_id:06d}"

        # Use pytak.gen_cot_xml for proper CoT structure (like send.py does)
        cot = pytak.gen_cot_xml(
            lat=str(lat),
            lon=str(lon),
            ce="50",
            le="50",
            hae="100",
            uid=uid,
            cot_type="a-f-A",  # Friendly air - matches ADS-B aircraft type
            stale=300
        )
        cot.set("access", "Undefined")
        cot.set("qos", "1-r-c")

        # Get the detail element and add required sub-elements
        detail = cot.find("detail")

        # Contact element - required for callsign display
        contact = ET.SubElement(detail, "contact")
        contact.set("callsign", callsign)

        # Track element - required for movement/course display
        track = ET.SubElement(detail, "track")
        track.set("course", str((index * 10) % 360))  # Vary course
        track.set("speed", "50")  # ~100 knots in m/s

        # Minimal remarks
        remarks = ET.SubElement(detail, "remarks")
        remarks.text = f"{callsign}"

        return b"\n".join([pytak.DEFAULT_XML_DECLARATION, ET.tostring(cot)])

    async def run(self):
        """Run the benchmark."""
        Logger.info("Starting benchmark...")
        Logger.info("  Target count: %s", self.target_count if self.target_count else "unlimited")
        Logger.info("  Rate limit: %s msg/s", self.rate if self.rate > 0 else "unlimited")
        Logger.info("  Duration: %s seconds", self.duration if self.duration else "unlimited")
        Logger.info("  Unique tracks: %s", self.unique_tracks if self.unique_tracks > 0 else "all unique")

        self.stats.start_time = time.time()
        index = 0
        interval = 1.0 / self.rate if self.rate > 0 else 0

        try:
            while True:
                # Check termination conditions
                if self.target_count and index >= self.target_count:
                    Logger.info("Reached target count of %d messages", self.target_count)
                    break

                if self.duration and (time.time() - self.stats.start_time) >= self.duration:
                    Logger.info("Reached duration limit of %d seconds", self.duration)
                    break

                # Generate and send message
                send_start = time.time()
                try:
                    cot_event = self.generate_cot_event(index)
                    await self.put_queue(cot_event)

                    # Track latency (time to queue)
                    latency_ms = (time.time() - send_start) * 1000
                    self.stats.total_latency_ms += latency_ms
                    self.stats.min_latency_ms = min(self.stats.min_latency_ms, latency_ms)
                    self.stats.max_latency_ms = max(self.stats.max_latency_ms, latency_ms)
                    self.stats.total_sent += 1

                except Exception as e:
                    Logger.error("Error sending message %d: %s", index, e)
                    self.stats.total_errors += 1

                index += 1

                # Progress logging every 1000 messages
                if index % 1000 == 0:
                    elapsed = time.time() - self.stats.start_time
                    current_rate = index / elapsed if elapsed > 0 else 0
                    Logger.info("Progress: %d messages sent (%.1f msg/s)", index, current_rate)

                # Rate limiting
                if interval > 0:
                    elapsed = time.time() - send_start
                    sleep_time = interval - elapsed
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            Logger.info("Benchmark cancelled")
        finally:
            self.stats.end_time = time.time()

        # Allow queue to drain
        Logger.info("Waiting for queue to drain...")
        await asyncio.sleep(2)

        print(self.stats.report())


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="TAK Server Benchmarking Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --count 1000 --rate 100     # Send 1000 messages at 100/sec
  %(prog)s --count 5000 --rate 0       # Send 5000 messages as fast as possible
  %(prog)s --duration 60 --rate 50     # Send for 60 seconds at 50/sec
  %(prog)s --count 1000                # Send 1000 messages at default rate

Environment Variables:
  COT_URL                    TAK server URL (default: tls://localhost:8089)
  PYTAK_TLS_CLIENT_CERT      Path to client certificate
  PYTAK_TLS_CLIENT_PASSWORD  Certificate password
        """
    )

    parser.add_argument(
        "--count", "-c",
        type=int,
        default=100,
        help="Number of messages to send (default: 100)"
    )

    parser.add_argument(
        "--rate", "-r",
        type=float,
        default=10,
        help="Messages per second, 0 for unlimited (default: 10)"
    )

    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        help="Maximum duration in seconds (optional)"
    )

    parser.add_argument(
        "--cot-url",
        type=str,
        default=None,
        help="TAK server URL (overrides COT_URL env var)"
    )

    parser.add_argument(
        "--cert",
        type=str,
        default=None,
        help="Path to TLS client certificate (overrides PYTAK_TLS_CLIENT_CERT)"
    )

    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="TLS certificate password (overrides PYTAK_TLS_CLIENT_PASSWORD)"
    )

    parser.add_argument(
        "--base-lat",
        type=float,
        default=40.7128,
        help="Base latitude for generated points (default: 40.7128)"
    )

    parser.add_argument(
        "--base-lon",
        type=float,
        default=-74.0060,
        help="Base longitude for generated points (default: -74.0060)"
    )

    parser.add_argument(
        "--unique-tracks", "-u",
        type=int,
        default=10,
        help="Number of unique tracks to cycle through (0 = all unique, default: 10)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()

    # Set up logging
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Build configuration
    cot_url = args.cot_url or os.getenv("COT_URL", "tls://localhost:8089")
    tls_cert = args.cert or os.getenv("PYTAK_TLS_CLIENT_CERT", "certs/funuser3.p12")
    tls_password = args.password or os.getenv("PYTAK_TLS_CLIENT_PASSWORD", "atakatak")

    # Validate certificate exists
    if not os.path.exists(tls_cert):
        Logger.error("Certificate file not found: %s", tls_cert)
        Logger.error("Set PYTAK_TLS_CLIENT_CERT or use --cert to specify certificate path")
        sys.exit(1)

    config = ConfigParser()
    config["benchmark"] = {
        "COT_URL": cot_url,
        "PYTAK_TLS_CLIENT_PASSWORD": tls_password,
        "PYTAK_TLS_DONT_CHECK_HOSTNAME": "1",
        "PYTAK_TLS_DONT_VERIFY": "1",
        "PYTAK_TLS_CLIENT_CERT": tls_cert,
        "MAX_OUT_QUEUE": "10000",  # Large queue for benchmarking
        "MAX_IN_QUEUE": "10000",
        "BASE_LAT": str(args.base_lat),
        "BASE_LON": str(args.base_lon),
    }

    config = config["benchmark"]

    Logger.info("TAK Server Benchmark")
    Logger.info("=" * 40)
    Logger.info("Target URL: %s", cot_url)
    Logger.info("Certificate: %s", tls_cert)
    Logger.info("Message Count: %s", args.count)
    Logger.info("Rate Limit: %s msg/s", args.rate if args.rate > 0 else "unlimited")
    if args.duration:
        Logger.info("Duration Limit: %s seconds", args.duration)
    Logger.info("=" * 40)

    # Initialize pytak CLI tool
    clitool = pytak.CLITool(config)

    try:
        await clitool.setup()
        Logger.info("Connected to TAK server successfully")
    except Exception as e:
        Logger.error("Failed to connect to TAK server at %s: %s", cot_url, e)
        sys.exit(1)

    # Create and run benchmark
    benchmark = BenchmarkSerializer(
        clitool.tx_queue,
        config,
        count=args.count,
        rate=args.rate,
        duration=args.duration,
        unique_tracks=args.unique_tracks
    )

    clitool.add_tasks({benchmark})

    try:
        await clitool.run()
    except KeyboardInterrupt:
        Logger.info("Benchmark interrupted by user")
        print(benchmark.stats.report())


if __name__ == "__main__":
    asyncio.run(main())
