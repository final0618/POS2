import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BROWSER = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


class AdminMembersHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path != "/test":
            return super().do_GET()
        html = (WEB / "admin.html").read_text(encoding="utf-8")
        mock = """
        <script>
        const alice={id:'a',phone:'0911111111',name:'Alice',status:'active',available_points:30,created_at:'2026-01-01T00:00:00Z'};
        const bob={id:'b',phone:'0922222222',name:'Bob',status:'disabled',available_points:0,created_at:'2026-01-02T00:00:00Z'};
        const tx=(kind,points_delta)=>({kind,points_delta,created_at:'2026-01-03T00:00:00Z',order_id:'sample'});
        window.fetch=async path=>{
          const url=new URL(path,location.origin);
          let data;
          if(url.pathname==='/api/admin/session') data={authenticated:true,username:'staff'};
          else if(url.pathname==='/api/admin/orders') data={orders:[]};
          else if(url.pathname==='/api/admin/menu') data={items:[]};
          else if(url.pathname==='/api/admin/members') {
            const query=url.searchParams.get('query');
            data=query==='Bob'?{members:[bob],has_more:false}:
              url.searchParams.get('offset')==='0'?{members:[alice],has_more:true}:{members:[bob],has_more:false};
          } else if(url.pathname==='/api/admin/members/a/transactions') {
            data=url.searchParams.get('offset')==='0'
              ?{member:alice,transactions:[tx('earn',130),tx('redeem',-100)],has_more:true}
              :{member:alice,transactions:[tx('reversal',100)],has_more:false};
          } else throw new Error('Unexpected request');
          return {ok:true,status:200,json:async()=>data};
        };
        window.addEventListener('load',()=>setTimeout(()=>{
          document.querySelector('#membersTab').click();
          setTimeout(()=>{
            let ok=document.querySelector('#memberRows').textContent.includes('Alice') &&
              document.querySelector('#memberRows').textContent.includes('30 點');
            document.querySelector('#loadMoreMembers').click();
            setTimeout(()=>{
              ok=ok && document.querySelector('#memberRows').textContent.includes('Bob');
              document.querySelector('#memberRows button').click();
              setTimeout(()=>{
                const list=document.querySelector('#memberTransactions');
                ok=ok && document.querySelector('#memberDetailSummary').textContent.includes('30 點') &&
                  list.children.length===2 && list.children[1].classList.contains('transaction-redeem');
                document.querySelector('#loadMoreMemberTransactions').click();
                setTimeout(()=>{
                  ok=ok && list.children.length===3 && list.textContent.includes('交易沖銷');
                  document.querySelector('#memberSearch').value='Bob';
                  document.querySelector('#memberSearchForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
                  setTimeout(()=>{
                    const rows=document.querySelector('#memberRows').textContent;
                    ok=ok && rows.includes('Bob') && !rows.includes('Alice') && document.querySelector('#memberDetail').hidden;
                    const result=document.createElement('div');result.id='ui-test-result';result.textContent=ok?'PASS':'FAIL';document.body.append(result);
                  },100);
                },100);
              },100);
            },100);
          },100);
        },100));
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
class AdminMembersUITests(unittest.TestCase):
    def test_member_search_and_history_pagination(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AdminMembersHandler)
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
