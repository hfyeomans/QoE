"""
Quality of Experience (QoE) Testing Script
-----------------------------------------
This script uses Python, Selenium, and headless Chrome to measure various
performance metrics for a list of websites including:
- Page load time
- Above-the-fold load time
- Latency
- Time to first byte
- Error rate
- Time to interactive

Results are saved in a format viewable in a web browser.
"""

import time
import json
import statistics
import datetime
import os
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


class QoETester:
    def __init__(self, urls, iterations=3, timeout=60):
        """
        Initialize the QoE tester with a list of URLs to test.
        
        Args:
            urls (list): List of URLs to test
            iterations (int): Number of times to test each URL
            timeout (int): Maximum wait time for page load in seconds
        """
        self.urls = urls
        self.iterations = iterations
        self.timeout = timeout
        self.results = {}
        
        # Setup Chrome options
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Add performance logging capabilities
        self.chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        self.chrome_options.add_argument("--enable-automation")
        
    def setup_driver(self):
        """Set up and return a new WebDriver instance."""
        return webdriver.Chrome(options=self.chrome_options)
    
    def measure_ttfb(self, logs):
        """
        Extract Time to First Byte from performance logs.
        
        Args:
            logs: Performance logs from Chrome
            
        Returns:
            float: Time to First Byte in milliseconds
        """
        for log in logs:
            if log["message"]:
                message = json.loads(log["message"])
                if (
                    "message" in message
                    and "method" in message["message"]
                    and message["message"]["method"] == "Network.responseReceived"
                ):
                    params = message["message"].get("params", {})
                    if params.get("type") == "Document":
                        response = params.get("response", {})
                        timing = response.get("timing")
                        if timing:
                            # TTFB = receiveHeadersEnd - sendEnd
                            return timing.get("receiveHeadersEnd", 0) - timing.get("sendEnd", 0)
        return None
    
    def measure_above_fold_time(self, driver):
        """
        Measure time to render above-the-fold content.
        
        Args:
            driver: WebDriver instance
            
        Returns:
            float: Time to render above-the-fold content in milliseconds
        """
        try:
            script = """
            return performance.getEntriesByType('paint')
                .filter(entry => entry.name === 'first-contentful-paint')[0].startTime;
            """
            fcp = driver.execute_script(script)
            return fcp
        except Exception:
            return None
    
    def measure_time_to_interactive(self, driver):
        """
        Measure Time to Interactive (TTI).
        
        Args:
            driver: WebDriver instance
            
        Returns:
            float: Time to Interactive in milliseconds
        """
        try:
            script = """
            const observer = new PerformanceObserver((list) => {
                const entries = list.getEntries();
                for (const entry of entries) {
                    if (entry.name === 'TTI') {
                        return entry.startTime;
                    }
                }
            });
            
            // Register observer and start timing
            observer.observe({entryTypes: ['measure']});
            
            // Create a simple way to detect interactivity
            // When page is interactive, most elements should be clickable
            const allElements = document.querySelectorAll('a, button, input');
            if (allElements.length > 0) {
                performance.mark('interactive_elements_found');
                performance.measure('TTI', 'navigationStart', 'interactive_elements_found');
                const tti = performance.getEntriesByName('TTI')[0];
                return tti ? tti.duration : null;
            }
            return null;
            """
            tti = driver.execute_script(script)
            if not tti:
                # Fallback: Use domInteractive as an approximation
                timing_script = "return window.performance.timing.domInteractive - window.performance.timing.navigationStart;"
                tti = driver.execute_script(timing_script)
            return tti
        except Exception:
            return None
    
    def test_url(self, url):
        """
        Test a single URL and collect metrics.
        
        Args:
            url (str): URL to test
            
        Returns:
            dict: Metrics for the URL
        """
        metrics = {
            "page_load_time": [],
            "above_fold_time": [],
            "ttfb": [],
            "time_to_interactive": [],
            "errors": 0,
            "error_messages": []
        }
        
        for i in range(self.iterations):
            driver = None
            try:
                start_time = time.time()
                driver = self.setup_driver()
                driver.set_page_load_timeout(self.timeout)
                
                # Navigate to the URL
                driver.get(url)
                
                # Measure page load time
                page_load_time = (time.time() - start_time) * 1000  # Convert to ms
                metrics["page_load_time"].append(page_load_time)
                
                # Get performance logs
                logs = driver.get_log("performance")
                
                # Measure Time to First Byte
                ttfb = self.measure_ttfb(logs)
                if ttfb:
                    metrics["ttfb"].append(ttfb)
                
                # Measure Above-the-fold load time
                above_fold_time = self.measure_above_fold_time(driver)
                if above_fold_time:
                    metrics["above_fold_time"].append(above_fold_time)
                
                # Measure Time to Interactive
                tti = self.measure_time_to_interactive(driver)
                if tti:
                    metrics["time_to_interactive"].append(tti)
                
            except TimeoutException:
                metrics["errors"] += 1
                metrics["error_messages"].append(f"Timeout loading {url}")
            except WebDriverException as e:
                metrics["errors"] += 1
                metrics["error_messages"].append(f"WebDriver error: {str(e)}")
            except Exception as e:
                metrics["errors"] += 1
                metrics["error_messages"].append(f"Error: {str(e)}")
            finally:
                if driver:
                    driver.quit()
        
        # Calculate error rate
        error_rate = (metrics["errors"] / self.iterations) * 100
        
        # Calculate averages
        result = {
            "url": url,
            "error_rate": error_rate,
            "error_messages": metrics["error_messages"]
        }
        
        # Calculate average metrics if we have data
        for metric in ["page_load_time", "above_fold_time", "ttfb", "time_to_interactive"]:
            if metrics[metric]:
                result[metric] = statistics.mean(metrics[metric])
            else:
                result[metric] = None
        
        return result
    
    def run_tests(self):
        """Run tests for all URLs and store the results."""
        for url in self.urls:
            print(f"Testing {url}...")
            result = self.test_url(url)
            domain = urlparse(url).netloc
            self.results[domain] = result
            print(f"Completed testing {url}")
        
        return self.results
    
    def generate_report(self, output_dir="reports"):
        """
        Generate an HTML report for the test results.
        
        Args:
            output_dir (str): Directory to save the report
            
        Returns:
            str: Path to the generated report
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = os.path.join(output_dir, f"qoe_report_{timestamp}.html")
        
        # Create HTML report
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Quality of Experience Test Results</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    margin: 0;
                    padding: 20px;
                    color: #333;
                }
                h1 {
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }
                .summary {
                    margin: 20px 0;
                    padding: 15px;
                    background-color: #f8f9fa;
                    border-radius: 5px;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }
                th, td {
                    padding: 12px 15px;
                    border: 1px solid #ddd;
                    text-align: left;
                }
                th {
                    background-color: #3498db;
                    color: white;
                    position: sticky;
                    top: 0;
                }
                tr:nth-child(even) {
                    background-color: #f2f2f2;
                }
                .error {
                    color: #e74c3c;
                }
                .domain {
                    font-weight: bold;
                }
                .chart-container {
                    height: 400px;
                    margin: 30px 0;
                }
                .footer {
                    margin-top: 30px;
                    text-align: center;
                    font-size: 0.8em;
                    color: #7f8c8d;
                }
            </style>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body>
            <h1>Quality of Experience Test Results</h1>
            <div class="summary">
                <p><strong>Test Date:</strong> """ + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
                <p><strong>Number of Sites Tested:</strong> """ + str(len(self.results)) + """</p>
            </div>
            
            <h2>Results Table</h2>
            <table>
                <thead>
                    <tr>
                        <th>Domain</th>
                        <th>Page Load Time (ms)</th>
                        <th>Above-fold Time (ms)</th>
                        <th>Time to First Byte (ms)</th>
                        <th>Time to Interactive (ms)</th>
                        <th>Error Rate (%)</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        # Add data rows
        domains = []
        page_load_times = []
        above_fold_times = []
        ttfbs = []
        ttis = []
        
        for domain, data in self.results.items():
            domains.append(domain)
            page_load_times.append(data.get("page_load_time", 0) or 0)
            above_fold_times.append(data.get("above_fold_time", 0) or 0)
            ttfbs.append(data.get("ttfb", 0) or 0)
            ttis.append(data.get("time_to_interactive", 0) or 0)
            
            html += f"""
                <tr>
                    <td class="domain">{domain}</td>
                    <td>{"%.2f" % data.get("page_load_time", "N/A") if data.get("page_load_time") else "N/A"}</td>
                    <td>{"%.2f" % data.get("above_fold_time", "N/A") if data.get("above_fold_time") else "N/A"}</td>
                    <td>{"%.2f" % data.get("ttfb", "N/A") if data.get("ttfb") else "N/A"}</td>
                    <td>{"%.2f" % data.get("time_to_interactive", "N/A") if data.get("time_to_interactive") else "N/A"}</td>
                    <td>{"%.2f" % data.get("error_rate", 0)}%</td>
                </tr>
            """
            
            # Add error messages if any
            if data.get("error_messages"):
                html += f"""
                <tr>
                    <td colspan="6" class="error">
                        <strong>Errors:</strong><br>
                        {"<br>".join(data.get("error_messages", []))}
                    </td>
                </tr>
                """
        
        html += """
                </tbody>
            </table>
            
            <h2>Performance Charts</h2>
            
            <div class="chart-container">
                <canvas id="pageLoadChart"></canvas>
            </div>
            
            <div class="chart-container">
                <canvas id="ttfbChart"></canvas>
            </div>
            
            <div class="chart-container">
                <canvas id="timeToInteractiveChart"></canvas>
            </div>
            
            <script>
                // Page Load Time Chart
                const pageLoadCtx = document.getElementById('pageLoadChart').getContext('2d');
                new Chart(pageLoadCtx, {
                    type: 'bar',
                    data: {
                        labels: """ + json.dumps(domains) + """,
                        datasets: [{
                            label: 'Page Load Time (ms)',
                            data: """ + json.dumps(page_load_times) + """,
                            backgroundColor: 'rgba(52, 152, 219, 0.7)',
                            borderColor: 'rgba(52, 152, 219, 1)',
                            borderWidth: 1
                        }, {
                            label: 'Above-fold Time (ms)',
                            data: """ + json.dumps(above_fold_times) + """,
                            backgroundColor: 'rgba(46, 204, 113, 0.7)',
                            borderColor: 'rgba(46, 204, 113, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Page Load Times Comparison'
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: 'Time (ms)'
                                }
                            }
                        }
                    }
                });
                
                // TTFB Chart
                const ttfbCtx = document.getElementById('ttfbChart').getContext('2d');
                new Chart(ttfbCtx, {
                    type: 'bar',
                    data: {
                        labels: """ + json.dumps(domains) + """,
                        datasets: [{
                            label: 'Time to First Byte (ms)',
                            data: """ + json.dumps(ttfbs) + """,
                            backgroundColor: 'rgba(155, 89, 182, 0.7)',
                            borderColor: 'rgba(155, 89, 182, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Time to First Byte'
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: 'Time (ms)'
                                }
                            }
                        }
                    }
                });
                
                // Time to Interactive Chart
                const ttiCtx = document.getElementById('timeToInteractiveChart').getContext('2d');
                new Chart(ttiCtx, {
                    type: 'bar',
                    data: {
                        labels: """ + json.dumps(domains) + """,
                        datasets: [{
                            label: 'Time to Interactive (ms)',
                            data: """ + json.dumps(ttis) + """,
                            backgroundColor: 'rgba(231, 76, 60, 0.7)',
                            borderColor: 'rgba(231, 76, 60, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Time to Interactive'
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: 'Time (ms)'
                                }
                            }
                        }
                    }
                });
            </script>
            
            <div class="footer">
                <p>Generated on """ + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
            </div>
        </body>
        </html>
        """
        
        # Write the HTML report to file
        with open(report_file, "w") as f:
            f.write(html)
        
        # Also generate JSON data
        json_file = os.path.join(output_dir, f"qoe_data_{timestamp}.json")
        with open(json_file, "w") as f:
            json.dump(self.results, f, indent=4)
        
        print(f"Report generated: {report_file}")
        print(f"JSON data saved: {json_file}")
        
        return report_file


def main():
    """Main function to run the QoE tests."""
    # List of URLs to test
    urls = [
        "https://www.google.com",
        "https://www.amazon.com",
        "https://www.wikipedia.org",
        "https://www.github.com",
        "https://www.stackoverflow.com"
    ]
    
    # Create and run the tester
    tester = QoETester(urls, iterations=3, timeout=60)
    results = tester.run_tests()
    report_path = tester.generate_report()
    
    print(f"Testing completed. Open {report_path} in a web browser to view the results.")


if __name__ == "__main__":
    main()