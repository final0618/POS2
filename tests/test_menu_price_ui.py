import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


WEB = Path(__file__).resolve().parent.parent / "web"
BROWSER = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


class PricePageHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path != "/test":
            return super().do_GET()
        html = (WEB / "admin.html").read_text(encoding="utf-8")
        mock = """
        <script>
        const samples = [{competitor_name:'Example', product_name:'Toast', price:355,
          price_source_url:'https://example.com/menu', price_checked_at:'2026-11-06',
          price_notes:'similar product'}];
        const items = [
          {id:'one',name:'One',category:'Breakfast',price:195,is_available:1,
           description:'Description',badge:'Badge',image_url:'https://example.com/img',
           alt_text:'Alt',price_comparisons:samples,recommended_price:355},
          {id:'two',name:'Two',category:'Breakfast',price:100,is_available:1,
           description:'Description',badge:'Badge',image_url:'https://example.com/img',
           alt_text:'Alt',price_comparisons:[],recommended_price:null}];
        window.fetch = async path => ({ok:true,status:200,json:async () =>
          path.includes('/session') ? {authenticated:true,username:'test'} :
          path.includes('/orders') ? {orders:[]} : {items}});
        window.addEventListener('load', () => setTimeout(() => {
          document.querySelector('#menuTab').click();
          setTimeout(() => {
            const rows = document.querySelectorAll('#menuRows tr');
            rows[0].querySelector('button').click();
            const advice = document.querySelector('#menuPriceAdvice');
            const ok = rows.length === 2 && rows[0].textContent.includes('355') &&
              rows[1].textContent.includes('查無資料') &&
              advice.textContent.includes('Toast') && advice.textContent.includes('similar product') &&
              advice.querySelector('a').href === 'https://example.com/menu' &&
              document.querySelector('#menuPrice').value === '195';
            const result = document.createElement('div');
            result.id = 'ui-test-result';
            result.textContent = ok ? 'PASS' : 'FAIL';
            document.body.append(result);
          }, 50);
        }, 50));
        </script>
        """
        html = html.replace('<script src="admin.js" defer></script>', mock + '<script src="admin.js" defer></script>')
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(BROWSER.is_file(), "Microsoft Edge not available")
class MenuPriceUITests(unittest.TestCase):
    def test_menu_displays_sample_and_missing_data(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), PricePageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as profile:
                result = subprocess.run(
                    [str(BROWSER), "--headless", "--disable-gpu", "--no-first-run",
                     f"--user-data-dir={profile}", "--virtual-time-budget=5000", "--dump-dom",
                     f"http://127.0.0.1:{server.server_port}/test"],
                    capture_output=True, timeout=40, check=True,
                )
                self.assertIn('id="ui-test-result">PASS', result.stdout.decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
