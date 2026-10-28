import {execFileSync,spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
execFileSync(process.execPath,['scripts/build.mjs'],{stdio:'inherit',env:{...process.env,API_BASE_URL:'http://127.0.0.1:4174'}});
const python=process.env.BACKEND_PYTHON || (existsSync('../backend/.venv/bin/python')?resolve('../backend/.venv/bin/python'):'python3');
const child=spawn(python,['-m','uvicorn','serve_fake:create_fake_app','--factory','--app-dir','tests','--host','127.0.0.1','--port','4174'],{cwd:resolve('../backend'),stdio:'inherit'});
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>child.kill(signal));
child.on('error',error=>{console.error(error.message);process.exit(1);});
child.on('exit',code=>process.exit(code ?? 0));
