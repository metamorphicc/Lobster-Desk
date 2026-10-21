// Local artifact renderer only. It never starts the API or touches account data.
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'artifacts','agent-floor-film');
const token=randomBytes(24).toString('hex'),port=8766;
await mkdir(output,{recursive:true});
const fonts={
 '/mono.woff2':path.join(root,'node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2'),
 '/sans.woff2':path.join(root,'node_modules/@fontsource/space-grotesk/files/space-grotesk-latin-500-normal.woff2')
};
const server=createServer(async(req,res)=>{
 try{
  if(req.headers.host!==`127.0.0.1:${port}`){res.writeHead(403).end();return}
  if(req.method==='GET'&&req.url==='/'){
   const html=(await readFile(path.join(root,'media/agent-floor/scene.html'),'utf8')).replaceAll('__RENDER_TOKEN__',token);
   res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}).end(html);return;
  }
  if(req.method==='GET'&&fonts[req.url]){res.writeHead(200,{'Content-Type':'font/woff2'}).end(await readFile(fonts[req.url]));return}
  if(req.method==='POST'&&req.url==='/recording'){
   const presented=req.headers['x-render-session']||'';
   if(presented.length!==token.length||!timingSafeEqual(Buffer.from(presented),Buffer.from(token))||req.headers.origin!==`http://127.0.0.1:${port}`){res.writeHead(403).end();return}
   const type=req.headers['content-type']||'',extension=type.startsWith('video/mp4')?'mp4':type.startsWith('video/webm')?'webm':null;
   if(!extension){res.writeHead(415).end();return}
   const chunks=[];let size=0;req.setTimeout(30000,()=>req.destroy());
   for await(const chunk of req){size+=chunk.length;if(size>64*1024*1024){res.writeHead(413).end();req.destroy();return}chunks.push(chunk)}
   const filename=`claw-desk-agents-20s.${extension}`;
   await writeFile(path.join(output,filename),Buffer.concat(chunks));
   res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify({filename}));
   console.log(`Saved ${path.join(output,filename)} (${size} bytes).`);return;
  }
  res.writeHead(404).end();
 }catch{if(!res.headersSent)res.writeHead(500);res.end('Local rendering failed.');}
});
server.requestTimeout=35000;server.listen(port,'127.0.0.1',()=>console.log(`Film renderer: http://127.0.0.1:${port}/ — output stays in ignored artifacts/agent-floor-film.`));
