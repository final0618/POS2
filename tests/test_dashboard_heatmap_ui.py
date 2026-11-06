import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BROWSER = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


class HeatmapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path not in ("/test-dashboard", "/test-admin"):
            return super().do_GET()
        admin = self.path == "/test-admin"
        html = (WEB / ("admin.html" if admin else "dashboard.html")).read_text(encoding="utf-8")
        mock = """
        <script>
        const tables = Array.from({length:12},(_,i)=>({table_number:String(i+1).padStart(2,'0'),order_count:i<2?3:i===2?1:0}));
        const dashboard = {sales:{today:0,week:250,month:1000},sales_definition:'test',
          top_products:[],popular_times:[],table_counts:tables,generated_at:'2026-11-06T15:00:00+08:00',
          daily_sales_week:[{date:'2026-11-01',amount:0},{date:'2026-11-02',amount:250},
            {date:'2026-11-03',amount:1000},{date:'2026-11-04',amount:0},
            {date:'2026-11-05',amount:0},{date:'2026-11-06',amount:0},
            {date:'2026-11-07',amount:null}]};
        window.fetch = async path => ({ok:true,status:200,json:async () =>
          path.includes('/session') ? {authenticated:true,username:'test'} :
          path.includes('/dashboard') ? dashboard :
          path.includes('/orders') ? {orders:[]} : {items:[]}});
        window.addEventListener('load', () => setTimeout(() => {
          const admin = document.querySelector('#overviewTab');
          if (admin) admin.click();
          setTimeout(() => {
            const list = document.querySelector(admin ? '#adminTableHeatmap' : '#tableHeatmap');
            const summary = document.querySelector(admin ? '#adminTableHeatmapSummary' : '#tableHeatmapSummary');
            const tiles = list.querySelectorAll('li');
            const bars = [...document.querySelectorAll('.sales-bar')];
            const amounts = [...document.querySelectorAll('.sales-metric strong')];
            const daily = [...document.querySelectorAll('.daily-sales-item')];
            const ok = tiles.length===12 && tiles[0].textContent.includes('01 桌') &&
              tiles[0].textContent.includes('3 單') && tiles[0].dataset.heat==='4' &&
              tiles[2].dataset.heat==='2' && tiles[3].dataset.heat==='0' &&
              summary.textContent.includes('01 桌、02 桌') &&
              bars.map(bar=>bar.style.width).join(',')==='0%,25%,100%' &&
              amounts[1].textContent.includes('250') && amounts[2].textContent.includes('1,000') &&
              daily.length===7 && daily[0].textContent.includes('11/01 週日') &&
              daily[1].querySelector('.daily-sales-bar').style.width==='25%' &&
              daily[2].querySelector('.daily-sales-bar').style.width==='100%' &&
              daily[6].textContent.includes('尚未到');
            dashboard.sales = {today:0,week:0,month:0};
            document.querySelector(admin ? '#refreshAdminDashboard' : '#refreshDashboard').click();
            setTimeout(() => {
              const zero = bars.every(bar=>bar.style.width==='0%') &&
                amounts.every(amount=>amount.textContent.includes('0'));
              const result = document.createElement('div');
              result.id = 'ui-test-result'; result.textContent = ok && zero ? 'PASS' : 'FAIL';
              document.body.append(result);
            }, 100);
          }, 100);
        }, 100));
        </script>
        """
        html = html.replace('<script src="table-heatmap.js" defer></script>',
                            mock + '<script src="table-heatmap.js" defer></script>')
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(BROWSER.is_file(), "Microsoft Edge not available")
class DashboardHeatmapUITests(unittest.TestCase):
    def test_heatmap_in_both_dashboards(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), HeatmapHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ("test-dashboard", "test-admin"):
                with self.subTest(page=path), tempfile.TemporaryDirectory() as profile:
                    result = subprocess.run(
                        [str(BROWSER), "--headless", "--disable-gpu", "--no-first-run",
                         f"--user-data-dir={profile}", "--virtual-time-budget=5000", "--dump-dom",
                         f"http://127.0.0.1:{server.server_port}/{path}"],
                        capture_output=True, timeout=40, check=True,
                    )
                    self.assertIn('id="ui-test-result">PASS', result.stdout.decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
