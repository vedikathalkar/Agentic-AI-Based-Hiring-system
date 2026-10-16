import assert from 'node:assert';
import { parseApplicationQuery as P, matchApplications as M } from '../src/utils/appSearch.js';
const mk=(id,title,state,cur,o={})=>({application_id:id,job_title:title,status:o.status||'submitted',assessment_status:o.as||'not_started',final_score:o.fs??null,test_score:o.ts??null,applied_at:o.at||new Date().toISOString(),pipeline:{outcome:{state,current:cur}}});
const apps=[mk(1,'Data Analyst','stopped','assessment',{status:'rejected',as:'completed',fs:55}),
 mk(2,'React Developer','in_progress','interview',{status:'shortlisted',as:'completed',fs:82}),
 mk(3,'Python Engineer','in_progress','assessment'),
 mk(4,'Data Engineer','in_progress','skill'),
 mk(5,'Backend Dev','completed','offer',{status:'hired',as:'completed',fs:90}),
 mk(6,'Old Role','in_progress','assessment',{at:'2020-01-01T00:00:00'})];
const ids=(q,e)=>M(apps,P(q).filters,e).map(a=>a.application_id);
assert.deepEqual(ids('rejected data roles'),[1]);
assert.deepEqual(ids('shortlisted'),[2]);
assert.deepEqual(ids('pending assessments'),[3,4,6]);
assert.deepEqual(ids('completed assessments'),[1,2,5]);
assert.deepEqual(ids('score above 80'),[2,5]);
assert.deepEqual(ids('python'),[3]);
assert.deepEqual(ids('this month'),[1,2,3,4,5]);
assert.deepEqual(ids('hired'),[5]);
assert.deepEqual(ids('being screened'),[4]);
assert.deepEqual(ids('',{stage:'stopped'}),[1]);
assert.equal(P('rejected score above 70').understood.length,2);
assert.deepEqual(ids('nothing matches xyz'),[]);
console.log('appSearch OK');
// returnTo logic mirrored from AuthPage
const roleForPath=(p)=>(p==='/admin'||p.startsWith('/admin/'))?'admin':(p==='/hr'||p.startsWith('/hr/'))?'hr':'candidate';
const HOME={talent:'/dashboard',ent:'/hr'};
const returnTo=(from,a)=>{if(typeof from!=='string'||!from.startsWith('/')||from.startsWith('//'))return HOME[a];const p=roleForPath(from.split(/[?#]/)[0]);return p===(a==='ent'?'hr':'candidate')?from:HOME[a]};
assert.equal(returnTo('/hr/jobs','talent'),'/dashboard');
assert.equal(returnTo('/hr','talent'),'/dashboard');
assert.equal(returnTo('/applications?x=1','talent'),'/applications?x=1');
assert.equal(returnTo('/applications','ent'),'/hr');
assert.equal(returnTo('/hr/jobs?id=2','ent'),'/hr/jobs?id=2');
assert.equal(returnTo(undefined,'ent'),'/hr');
assert.equal(returnTo('//evil.com','talent'),'/dashboard');
console.log('returnTo OK');
