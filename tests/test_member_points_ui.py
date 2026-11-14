import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BROWSER = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


class MemberPointsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path != "/test":
            return super().do_GET()
        html = (WEB / "member.html").read_text(encoding="utf-8")
        mock = """
        <script>
        const transaction = (kind, points_delta) => ({kind,points_delta,created_at:'2026-11-14T05:00:00Z',order_id:null});
        window.fetch = async path => ({ok:true,json:async () =>
          path.includes('/transactions') ? (path.includes('offset=0')
            ? {transactions:[transaction('earn',22),transaction('redeem',-100),transaction('expire',-10)],has_more:true}
            : {transactions:[transaction('redeem',-200),transaction('reversal',100)],has_more:false}) :
          path.includes('/session') ? {authenticated:true,phone:'1234'} :
          {available_points:100,expiring:[]}});
        window.addEventListener('load',()=>setTimeout(()=>{
          document.querySelector('#loadMore').click();
          setTimeout(()=>{
            const list=document.querySelector('#transactionsList');
            const rows=[...list.querySelectorAll('li')];
            const colors=rows.map(row=>getComputedStyle(row).color);
            const normal=getComputedStyle(list).color;
            const ok=rows.length===5 && colors[1]==='rgb(199, 44, 49)' &&
              colors[3]==='rgb(199, 44, 49)' &&
              [0,2,4].every(i=>colors[i]===normal);
            const result=document.createElement('div');
            result.id='ui-test-result';result.textContent=ok?'PASS':'FAIL';document.body.append(result);
          },100);
        },100));
        </script>
        """
        html = html.replace('<script src="member.js" defer></script>', mock + '<script src="member.js" defer></script>')
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(BROWSER.is_file(), "Microsoft Edge not available")
class MemberPointsUITests(unittest.TestCase):
    def test_only_redemptions_are_red_across_pages(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), MemberPointsHandler)
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
