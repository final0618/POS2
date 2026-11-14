import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BROWSER = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


class CheckoutHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path not in ("/test-member", "/test-guest", "/test-failure"):
            return super().do_GET()
        mode = self.path.removeprefix("/test-")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        mock = """
        <script>
        const mode = MODE;
        let balance = 0, submitted = null;
        const item = {id:'test',name:'Test',category:'Breakfast',price:220,description:'Test',badge:'Test',image:'',alt:'Test'};
        window.fetch = async (path,options={}) => {
          if (path === '/api/menu') return {ok:true,json:async()=>({items:[item]})};
          if (path === '/api/members/session') return {ok:mode!=='failure',json:async()=>({authenticated:mode==='member'})};
          if (path === '/api/members/me/points') return {ok:true,json:async()=>({available_points:balance})};
          if (path === '/api/orders') {
            submitted=JSON.parse(options.body);
            return {ok:true,json:async()=>({order:{id:'test-order',table_number:'01',items:[{name:'Test',quantity:1,subtotal:220}],total_amount:220,points_discount_amount:submitted.points_redeemed/100,payable_amount:220-submitted.points_redeemed/100}})};
          }
          throw new Error('Unexpected request');
        };
        window.addEventListener('load',()=>setTimeout(()=>{
          const table=document.querySelector('#tableSelect');table.value='01';table.dispatchEvent(new Event('change'));
          document.querySelector('[data-add]').click();
          balance=391;
          document.querySelector('#checkoutButton').click();
          setTimeout(()=>{
            const panel=document.querySelector('#redemptionPanel');
            const input=document.querySelector('#redeemPoints');
            const button=document.querySelector('#placeOrderButton');
            let ok;
            if(mode==='failure'){
              ok=button.disabled && !document.querySelector('#orderError').hidden && submitted===null;
            }else if(mode==='guest'){
              ok=panel.hidden && !button.disabled;
              button.click();
            }else{
              ok=!panel.hidden && input.max==='300' && document.querySelector('#redemptionHint').textContent.includes('391');
              input.value='300';input.dispatchEvent(new Event('input'));
              ok=ok && document.querySelector('#redemptionPreview').textContent.includes('217');
              button.click();
            }
            setTimeout(()=>{
              if(mode!=='failure') ok=ok && submitted && submitted.points_redeemed===(mode==='member'?300:0) && document.querySelector('#successDialog').open;
              const result=document.createElement('div');result.id='ui-test-result';result.textContent=ok?'PASS':'FAIL';document.body.append(result);
            },100);
          },100);
        },100));
        </script>
        """.replace("MODE", repr(mode))
        html = html.replace('<script src="app.js" defer></script>', mock + '<script src="app.js" defer></script>')
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(BROWSER.is_file(), "Microsoft Edge not available")
class CheckoutPointsUITests(unittest.TestCase):
    def test_fresh_balance_guest_and_failed_lookup(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CheckoutHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for mode in ("member", "guest", "failure"):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as profile:
                    result = subprocess.run(
                        [str(BROWSER), "--headless", "--disable-gpu", "--no-first-run",
                         f"--user-data-dir={profile}", "--virtual-time-budget=5000", "--dump-dom",
                         f"http://127.0.0.1:{server.server_port}/test-{mode}"],
                        capture_output=True, timeout=40, check=True,
                    )
                    self.assertIn('id="ui-test-result">PASS', result.stdout.decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
