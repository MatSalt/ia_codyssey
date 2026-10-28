import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve, extname, sep} from 'node:path';
const root=resolve('.');
createServer(async (req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  if(pathname==='/config.js'){res.setHeader('Content-Type','text/javascript');res.end('window.APP_CONFIG={API_BASE_URL:window.location.origin}');return;}
  const file=resolve(root, '.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(root+sep)){res.writeHead(403).end();return;}
  try {const data=await readFile(file);res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css'})[extname(file)]||'application/octet-stream');res.end(data);}catch{res.writeHead(404).end();}
}).listen(4173,'127.0.0.1');
