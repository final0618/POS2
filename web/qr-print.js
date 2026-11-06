const siteUrlInput=document.querySelector("#siteUrl");
const generateButton=document.querySelector("#generateButton");
const downloadButton=document.querySelector("#downloadButton");
const printButton=document.querySelector("#printButton");
const urlStatus=document.querySelector("#urlStatus");
const qrOutput=document.querySelector("#qrOutput");
let qrReady=false;

function showStatus(message,state){urlStatus.textContent=message;urlStatus.dataset.state=state}
function validateUrl(value){try{const url=new URL(value.trim());if(!/^https?:$/.test(url.protocol))return{valid:false,message:"網址必須以 https:// 或 http:// 開頭。"};if(["localhost","127.0.0.1","::1"].includes(url.hostname))return{valid:false,message:"這是本機測試網址，手機無法從店內連線。請改用公開網站網址。"};if(url.hostname.endsWith(".example")||url.hostname==="example.com")return{valid:false,message:"請將範例網址換成實際公開的點餐網址。"};return{valid:true,url}}catch{return{valid:false,message:"請輸入完整網址，例如 https://your-shop.tw/web/ 。"}}}
function createQr(){const result=validateUrl(siteUrlInput.value);if(!result.valid){qrOutput.replaceChildren(Object.assign(document.createElement("span"),{textContent:"設定網址後\nQR Code 會顯示在這裡"}));qrReady=false;downloadButton.disabled=true;printButton.disabled=true;showStatus(result.message,"error");return}qrOutput.replaceChildren();try{new QRCode(qrOutput,{text:result.url.href,width:320,height:320,colorDark:"#292724",colorLight:"#ffffff",correctLevel:QRCode.CorrectLevel.H});qrReady=true;downloadButton.disabled=false;printButton.disabled=false;showStatus(`QR Code 已產生：${result.url.href}`,"success")}catch(error){qrReady=false;downloadButton.disabled=true;printButton.disabled=true;showStatus(`無法產生 QR Code：${error.message}`,"error")}}
generateButton.addEventListener("click",createQr);siteUrlInput.addEventListener("keydown",event=>{if(event.key==="Enter")createQr()});
downloadButton.addEventListener("click",()=>{if(!qrReady)return;const canvas=qrOutput.querySelector("canvas"),image=qrOutput.querySelector("img"),dataUrl=canvas?.toDataURL("image/png")||image?.src;if(!dataUrl){showStatus("瀏覽器尚未完成 QR 圖片，請稍後再試。","error");return}const link=document.createElement("a");link.href=dataUrl;link.download="good-morning-order-qr.png";link.click()});
printButton.addEventListener("click",()=>{if(qrReady)window.print()});