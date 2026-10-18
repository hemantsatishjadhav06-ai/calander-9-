// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/agency-thread.js'), 'utf8');

function decisionMarkup({caseId='attempt-1', fingerprint='fingerprint-1', destination='account-1:instagram:native-1', action='existing', includeFingerprint=true, includeDestination=true, disabled=false, asHidden=false}={}) {
  const key = `receipt-1:${caseId}:${action}`;
  return `<details data-thread-details-key="receipt-decision-1"><summary>Check delivery</summary>
    <form data-thread-decision="${key}" ${includeDestination?`data-decision-destination="${destination}"`:''}>
      <input type="hidden" name="expected_attempt_id" value="${caseId}">
      ${includeFingerprint?`<input type="hidden" name="expected_fingerprint" value="${fingerprint}">`:''}
      <input type="${asHidden?'hidden':'text'}" name="native_post_id" value="">
      <input type="url" name="url" value=""><textarea name="reason"></textarea>
      <input type="checkbox" name="confirmed" ${disabled?'disabled':''}>
      <button>Record decision</button>
    </form>
  </details>`;
}

function markup({key='workspace-1:thread-home', ids=['one'], confirm='summary-1', claim='Verified price', error=false, reference='photo-1', style='brand', target='', addPhoto=true, decision=null, receipts=[]}={}) {
  const options = ['','photo-1','photo-2','none'].concat(addPhoto ? ['uploaded-photo'] : []);
  return `<section id="thread-home" data-agency-thread data-thread-key="${key}">
    <div id="thread-home-messages" role="log" data-thread-log>${ids.map(id=>`<div data-thread-message-id="${id}">${id}</div>`).join('')}
      <div data-thread-message-id="${confirm}" data-creative-brief="${confirm}">
        <p>${claim}</p><details data-thread-details-key="sources:${confirm}"><summary>Sources</summary><p>Evidence</p></details>
        <form data-confirm-brief="${confirm}"><input name="confirmation_message_id" value="${confirm}"><input type="checkbox" name="facts_confirmed"><button>Confirm</button></form>
      </div>
      ${decision ? decisionMarkup(decision) : ''}
      ${receipts.map(({id='receipt-1',status='Scheduled',account='Neopolis',nativeId=''})=>`<div data-platform-receipt="${id}" data-receipt-status="${status}" data-receipt-account="${account}" data-receipt-native-id="${nativeId}">${account} ${status}</div>`).join('')}
    </div>
    <button type="button" data-thread-new-messages hidden>New messages</button><span role="status" data-thread-announcement></span>
    <form data-thread-composer>${error ? '<p data-thread-error>Error</p>' : ''}
      <select name="target_brief_id">${['','draft-1','draft-2'].map(value=>`<option value="${value}" ${value===target?'selected':''}>${value}</option>`).join('')}</select>
      <textarea id="thread-home-body" name="body"></textarea>
      <details data-thread-details-key="composer:creative"><summary>Creative direction</summary>
        <select name="reference_id" data-current-choice="${reference}">${options.map(value=>`<option value="${value}" ${value===reference?'selected':''}>${value}</option>`).join('')}</select>
        <input id="thread-home-file" type="file" name="reference_upload">
        <select name="style_mode" data-current-choice="${style}">${['','brand','fresh'].map(value=>`<option value="${value}" ${value===style?'selected':''}>${value}</option>`).join('')}</select>
      </details>
      <input type="checkbox" name="is_internal"><button>Send</button>
    </form>
  </section>`;
}
function fixture(options) {
  const dom = new JSDOM(markup(options), {runScripts:'outside-only', url:'https://example.test/workspace/one/agency/thread/'});
  const win = dom.window;
  win.eval(script);
  win.document.dispatchEvent(new win.Event('DOMContentLoaded'));
  const query = selector=>win.document.querySelector(selector);
  const emit = (name, detail)=>win.document.dispatchEvent(new win.CustomEvent(name, {detail}));
  function geometry(log) {
    Object.defineProperty(log, 'clientHeight', {configurable:true,value:200});
    Object.defineProperty(log, 'scrollHeight', {configurable:true,value:1000});
  }
  geometry(query('[data-thread-log]'));
  function request(source='poll') {
    const xhr = {status:200};
    emit('htmx:beforeRequest', {elt:query(source==='poll' ? '[data-thread-log]' : source==='confirm' ? '[data-confirm-brief]' : '[data-thread-composer]'),xhr});
    return xhr;
  }
  function swap(xhr, options, source='poll') {
    const old = query(source==='poll' ? '[data-thread-log]' : '[data-agency-thread]');
    emit('htmx:beforeSwap',{target:old,xhr,shouldSwap:true});
    const template = win.document.createElement('template'); template.innerHTML = markup(options);
    const panel = template.content.firstElementChild;
    old.replaceWith(source==='poll' ? panel.querySelector('[data-thread-log]') : panel);
    geometry(query('[data-thread-log]'));
    emit('htmx:afterSwap',{target:query('[data-thread-log]'),xhr});
  }
  return {win,query,emit,request,swap};
}

test('poll preserves higher scroll, expanded evidence, exact-summary consent and focused checkbox',()=>{
  const f=fixture(); const log=f.query('[data-thread-log]'); log.scrollTop=125;
  f.query('[data-thread-details-key^="sources"]').open=true;
  const checkbox=f.query('[name=facts_confirmed]'); checkbox.checked=true; checkbox.focus();
  f.swap(f.request(),{ids:['one','two']});
  assert.equal(f.query('[data-thread-log]').scrollTop,125);
  assert.equal(f.query('[data-thread-details-key^="sources"]').open,true);
  assert.equal(f.query('[name=facts_confirmed]').checked,true);
  assert.equal(f.win.document.activeElement,f.query('[name=facts_confirmed]'));
  assert.equal(f.query('[data-thread-new-messages]').hidden,false);
  assert.match(f.query('[data-thread-announcement]').textContent,/A new message/);
});

test('new summary never inherits checked consent or expanded source disclosure',()=>{
  const f=fixture();f.query('[name=facts_confirmed]').checked=true;f.query('[data-thread-details-key^="sources"]').open=true;
  f.swap(f.request(),{confirm:'summary-2'});
  assert.equal(f.query('[name=facts_confirmed]').checked,false);
  assert.equal(f.query('[data-thread-details-key^="sources"]').open,false);
});

test('changed facts on same summary do not retain consent',()=>{
  const f=fixture();f.query('[name=facts_confirmed]').checked=true;
  f.swap(f.request(),{claim:'A different price'});
  assert.equal(f.query('[name=facts_confirmed]').checked,false);
});

test('a reader already at the bottom follows incoming messages',()=>{
  const f=fixture();f.query('[data-thread-log]').scrollTop=800;
  f.swap(f.request(),{ids:['one','two']});
  assert.equal(f.query('[data-thread-log]').scrollTop,1000);
  assert.equal(f.query('[data-thread-new-messages]').hidden,true);
});

test('successful send keeps draft target, uses authoritative committed photo/style, and clears sent text',()=>{
  const f=fixture();f.query('[name=body]').value='Generate a post';f.query('[name=target_brief_id]').value='draft-2';
  f.query('[name=reference_id]').value='photo-2';f.query('[name=style_mode]').value='fresh';
  f.swap(f.request('send'),{reference:'photo-2',style:'fresh'},'send');
  assert.equal(f.query('[name=target_brief_id]').value,'draft-2');
  assert.equal(f.query('[name=reference_id]').value,'photo-2');
  assert.equal(f.query('[name=style_mode]').value,'fresh');
  assert.equal(f.query('[name=body]').value,'');
});

test('new text and direction typed while a send is in flight survive that successful response',()=>{
  const f=fixture();f.query('[name=body]').value='First request';const xhr=f.request('send');
  f.query('[name=body]').value='Next thought';f.query('[name=reference_id]').value='photo-2';f.query('[name=style_mode]').value='fresh';
  f.swap(xhr,{reference:'photo-1',style:'brand'},'send');
  assert.equal(f.query('[name=body]').value,'Next thought');
  assert.equal(f.query('[name=reference_id]').value,'photo-2');
  assert.equal(f.query('[name=style_mode]').value,'fresh');
});

test('successful upload adopts new server reference rather than restoring previous current photo',()=>{
  const f=fixture();f.query('[name=body]').value='Use attached photo';
  f.swap(f.request('send'),{reference:'uploaded-photo'},'send');
  assert.equal(f.query('[name=reference_id]').value,'uploaded-photo');
});

test('validation error retains typed draft, dirty selectors and original file-input node',()=>{
  const f=fixture();f.query('[name=body]').value='Needs correction';f.query('[name=reference_id]').value='photo-2';f.query('[name=style_mode]').value='fresh';
  const file=f.query('[name=reference_upload]');Object.defineProperty(file,'files',{value:[new f.win.File(['x'],'reference.png',{type:'image/png',lastModified:1})]});
  f.swap(f.request('send'),{error:true},'send');
  assert.equal(f.query('[name=body]').value,'Needs correction');assert.equal(f.query('[name=reference_id]').value,'photo-2');
  assert.equal(f.query('[name=style_mode]').value,'fresh');assert.equal(f.query('[name=reference_upload]'),file);
  assert.equal(file.type,'file');assert.equal(file.files[0].name,'reference.png');
});

test('confirmation response preserves unrelated draft text in composer',()=>{
  const f=fixture();f.query('[name=body]').value='Unsent thought';
  f.swap(f.request('confirm'),{},'confirm');
  assert.equal(f.query('[name=body]').value,'Unsent thought');
});

test('another thread identity receives no carried draft or consent state',()=>{
  const f=fixture();f.query('[name=body]').value='Private draft';f.query('[name=facts_confirmed]').checked=true;
  f.swap(f.request('send'),{key:'workspace-2:thread-home'},'send');
  assert.equal(f.query('[name=body]').value,'');assert.equal(f.query('[name=facts_confirmed]').checked,false);
});

test('unchanged photo/style are omitted from HTMX while target always remains',()=>{
  const f=fixture();const parameters={reference_id:'photo-1',style_mode:'brand',target_brief_id:'draft-1'};
  f.emit('htmx:configRequest',{elt:f.query('[data-thread-composer]'),parameters});
  assert.deepEqual(parameters,{target_brief_id:'draft-1'});
  f.query('[name=reference_id]').value='none';f.query('[name=style_mode]').value='fresh';
  const changed={reference_id:'none',style_mode:'fresh',target_brief_id:'draft-1'};
  f.emit('htmx:configRequest',{elt:f.query('[data-thread-composer]'),parameters:changed});
  assert.deepEqual(changed,{reference_id:'none',style_mode:'fresh',target_brief_id:'draft-1'});
});

test('native formdata removes unchanged context too',()=>{
  const f=fixture();const data=new f.win.FormData();data.set('reference_id','photo-1');data.set('style_mode','brand');data.set('target_brief_id','draft-2');
  const event=new f.win.Event('formdata',{bubbles:false});Object.defineProperty(event,'formData',{value:data});
  f.query('[data-thread-composer]').dispatchEvent(event);
  assert.equal(data.has('reference_id'),false);assert.equal(data.has('style_mode'),false);assert.equal(data.get('target_brief_id'),'draft-2');
});

test('show-latest indicator is keyboard-focusable and clears unread state',()=>{
  const f=fixture();f.query('[data-thread-log]').scrollTop=100;f.swap(f.request(),{ids:['one','two']});
  f.query('[data-thread-new-messages]').click();
  assert.equal(f.query('[data-thread-log]').scrollTop,1000);assert.equal(f.query('[data-thread-new-messages]').hidden,true);
  assert.equal(f.win.document.activeElement,f.query('[data-thread-log]'));
});

test('polling does not steal focus moved outside the thread during request',()=>{
  const f=fixture();f.query('[name=facts_confirmed]').focus();const xhr=f.request();
  const outside=f.win.document.createElement('button');outside.textContent='Navigation';f.win.document.body.append(outside);outside.focus();
  f.swap(xhr,{ids:['one','two']});assert.equal(f.win.document.activeElement,outside);
});

test('successful send restores focus to its composer button instead of a confirmation button',()=>{
  const f=fixture();f.query('[name=body]').value='New request';f.query('[data-thread-composer] button').focus();
  f.swap(f.request('send'),{},'send');assert.equal(f.win.document.activeElement,f.query('[data-thread-composer] button'));
});

test('a reference removed by server context is never reintroduced by state restoration',()=>{
  const f=fixture({reference:'uploaded-photo'});f.query('[name=body]').value='New request';
  f.swap(f.request('send'),{reference:'photo-1',addPhoto:false},'send');
  assert.equal(f.query('[name=reference_id]').value,'photo-1');
  assert.equal(Array.from(f.query('[name=reference_id]').options).some(option=>option.value==='uploaded-photo'),false);
});

test('same delivery decision retains entered evidence, checked confirmation, details and field focus',()=>{
  const f=fixture({decision:{}});const form=f.query('[data-thread-decision]');
  form.elements.native_post_id.value='platform-123';form.elements.url.value='https://instagram.com/p/existing/';
  form.elements.reason.value='Checked the exact brand account and content.';form.elements.confirmed.checked=true;
  f.query('[data-thread-details-key="receipt-decision-1"]').open=true;form.elements.url.focus();
  f.swap(f.request(),{decision:{}});
  const fresh=f.query('[data-thread-decision]');
  assert.equal(fresh.elements.native_post_id.value,'platform-123');assert.equal(fresh.elements.url.value,'https://instagram.com/p/existing/');
  assert.equal(fresh.elements.reason.value,'Checked the exact brand account and content.');assert.equal(fresh.elements.confirmed.checked,true);
  assert.equal(f.query('[data-thread-details-key="receipt-decision-1"]').open,true);assert.equal(f.win.document.activeElement,fresh.elements.url);
  assert.equal(fresh.elements.expected_attempt_id.value,'attempt-1');assert.equal(fresh.elements.expected_fingerprint.value,'fingerprint-1');
});

for (const [name, change] of [
  ['delivery case', {caseId:'attempt-2'}],
  ['delivery fingerprint', {fingerprint:'fingerprint-2'}],
  ['native destination', {destination:'account-1:instagram:native-2'}],
  ['workspace account', {destination:'account-2:instagram:native-1'}],
  ['decision action', {action:'absent'}],
  ['missing destination guard', {includeDestination:false}],
  ['missing expected fingerprint', {includeFingerprint:false}],
]) {
  test(`changed ${name} never carries evidence, confirmation, details or focus`,()=>{
    const f=fixture({decision:{}});const form=f.query('[data-thread-decision]');
    form.elements.native_post_id.value='old-native-id';form.elements.url.value='https://instagram.com/p/old/';
    form.elements.reason.value='Old account evidence.';form.elements.confirmed.checked=true;form.elements.url.focus();
    f.query('[data-thread-details-key="receipt-decision-1"]').open=true;
    f.swap(f.request(),{decision:change});
    const fresh=f.query('[data-thread-decision]');
    assert.equal(fresh.elements.native_post_id.value,'');assert.equal(fresh.elements.url.value,'');assert.equal(fresh.elements.reason.value,'');
    assert.equal(fresh.elements.confirmed.checked,false);assert.equal(f.query('[data-thread-details-key="receipt-decision-1"]').open,false);
    assert.notEqual(f.win.document.activeElement,fresh.elements.url);
  });
}

test('receipt details-summary focus does not carry into a changed delivery case',()=>{
  const f=fixture({decision:{}});f.query('[data-thread-details-key="receipt-decision-1"] summary').focus();
  f.swap(f.request(),{decision:{caseId:'attempt-2'}});
  assert.notEqual(f.win.document.activeElement,f.query('[data-thread-details-key="receipt-decision-1"] summary'));
});

test('unchanged delivery case preserves an unchecked checkbox without submitting anything',()=>{
  const f=fixture({decision:{}});let submissions=0;
  f.win.document.addEventListener('submit',()=>submissions++);
  f.swap(f.request(),{decision:{}});
  assert.equal(f.query('[data-thread-decision]').elements.confirmed.checked,false);assert.equal(submissions,0);
});

test('new hidden or disabled delivery inputs never receive restored human decision data',()=>{
  const f=fixture({decision:{}});const form=f.query('[data-thread-decision]');
  form.elements.native_post_id.value='old-native-id';form.elements.confirmed.checked=true;
  f.swap(f.request(),{decision:{disabled:true,asHidden:true}});
  assert.equal(f.query('[data-thread-decision]').elements.native_post_id.value,'');
  assert.equal(f.query('[data-thread-decision]').elements.confirmed.checked,false);
});

test('unchanged receipt polling stays silent even while evidence inputs are edited',()=>{
  const receipts=[{status:'Scheduled'}];const f=fixture({receipts,decision:{}});
  f.query('[data-thread-decision]').elements.reason.value='PRIVATE account inspection note';
  f.query('[data-thread-decision]').elements.native_post_id.value='PRIVATE typed evidence';
  f.swap(f.request(),{receipts,decision:{}});
  assert.equal(f.query('[data-thread-announcement]').textContent,'');
});

test('publication status change announces the outcome without adding a transcript message',()=>{
  const f=fixture({receipts:[{status:'Scheduled'}]});
  f.swap(f.request(),{receipts:[{status:'Published',nativeId:'platform-123'}]});
  const announcement=f.query('[data-thread-announcement]').textContent;
  assert.match(announcement,/Posting status updated/);assert.match(announcement,/Neopolis: Published/);
  assert.match(announcement,/post ID recorded/);assert.doesNotMatch(announcement,/new message/);
});

test('new native delivery evidence and receipt count changes also produce announcements',()=>{
  const f=fixture({receipts:[{status:'Published'}]});
  f.swap(f.request(),{receipts:[{status:'Published',nativeId:'platform-123'}]});
  assert.match(f.query('[data-thread-announcement]').textContent,/post ID recorded/);
  f.swap(f.request(),{receipts:[{status:'Published',nativeId:'platform-123'},{id:'receipt-2',account:'More Space',status:'Recorded after account check'}]});
  assert.match(f.query('[data-thread-announcement]').textContent,/More Space: Recorded after account check/);
  assert.match(f.query('[data-thread-announcement]').textContent,/2 posting destinations shown/);
});
