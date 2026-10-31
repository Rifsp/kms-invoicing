'use strict';
const money=value=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:2}).format(value);
document.addEventListener('submit',event=>{const message=event.target.dataset.confirm;if(message&&!window.confirm(message))event.preventDefault();});
document.addEventListener('click',event=>{if(event.target.closest('[data-print]'))window.print();});
document.getElementById('menu-toggle')?.addEventListener('click',event=>{const button=event.currentTarget;const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));document.body.classList.toggle('nav-open',open);});

// Authenticated remote lookups: only the chosen option is in the original HTML.
let lookupIndex=0;
function enhanceSearchSelect(select){
 if(select.dataset.enhanced)return;select.dataset.enhanced='1';
 const wrapper=document.createElement('div');wrapper.className='search-select';select.before(wrapper);wrapper.append(select);
 const input=document.createElement('input');input.type='search';input.autocomplete='off';input.placeholder=select.dataset.searchKind==='product'?'Cari nama atau kode barang…':'Cari nama mitra…';input.id=(select.id||'lookup-'+(++lookupIndex))+'_search';
 input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
 const list=document.createElement('div');list.className='search-results';list.id=input.id+'_list';list.setAttribute('role','listbox');list.hidden=true;input.setAttribute('aria-controls',list.id);
 const originalRequired=select.required;input.required=originalRequired;select.required=false;select.classList.add('lookup-native');select.tabIndex=-1;
 if(select.id){const label=document.querySelector('label[for="'+CSS.escape(select.id)+'"]');if(label)label.htmlFor=input.id;}
 wrapper.append(input);document.body.append(list);let timer,controller,active=-1;
 function position(){if(list.hidden)return;const r=input.getBoundingClientRect();list.style.position='fixed';list.style.left=r.left+'px';list.style.right='auto';list.style.width=r.width+'px';list.style.top=(r.bottom+5)+'px';list.style.maxHeight=Math.max(120,Math.min(300,window.innerHeight-r.bottom-20))+'px';list.style.zIndex='100';}
 window.addEventListener('scroll',position,true);window.addEventListener('resize',position);
 function sync(){input.value=select.value?(select.selectedOptions[0]?.textContent||''):'';input.setCustomValidity('');}
 function close(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');}
 function choose(row){select.add(new Option(row.label,row.id,true,true));sync();close();select.dispatchEvent(new Event('change',{bubbles:true}));}
 async function search(){
  if(controller)controller.abort();controller=new AbortController();active=-1;
  list.replaceChildren();list.hidden=false;position();input.setAttribute('aria-expanded','true');list.textContent='Mencari…';
  try{
   const url=new URL(document.body.dataset.lookupUrl,window.location.origin);url.searchParams.set('kind',select.dataset.searchKind);url.searchParams.set('q',input.value);
   const response=await fetch(url,{signal:controller.signal});if(!response.ok)throw new Error('Search failed');const data=await response.json();list.replaceChildren();
   if(!data.results.length){list.textContent='Tidak ditemukan. Coba nama atau kode lain.';return;}
   data.results.forEach((row,index)=>{const option=document.createElement('button');option.type='button';option.id=list.id+'_'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=row.label;option.addEventListener('click',()=>choose(row));list.append(option);});
  }catch(error){if(error.name!=='AbortError')list.textContent='Pencarian gagal. Coba lagi atau masuk kembali.';}
 }
 input.addEventListener('input',()=>{select.value='';if(originalRequired)input.setCustomValidity('Pilih salah satu hasil pencarian.');select.dispatchEvent(new Event('change',{bubbles:true}));clearTimeout(timer);timer=setTimeout(search,220);});
 input.addEventListener('focus',()=>{if(!select.value)search();});
 input.addEventListener('keydown',event=>{
  const options=[...list.querySelectorAll('button')];
  if(event.key==='Escape'){close();return;}
  if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();if(list.hidden){search();return;}active=Math.max(0,Math.min(options.length-1,active+(event.key==='ArrowDown'?1:-1)));options.forEach((option,index)=>option.setAttribute('aria-selected',String(index===active)));if(options[active]){input.setAttribute('aria-activedescendant',options[active].id);options[active].scrollIntoView({block:'nearest'});}}
  if(event.key==='Enter'&&!list.hidden){event.preventDefault();if(active<0)active=0;options[active]?.click();}
 });
 document.addEventListener('click',event=>{if(!wrapper.contains(event.target)&&!list.contains(event.target))close();});
 select.addEventListener('change',()=>{if(select.value)sync();});sync();
}
document.querySelectorAll('select[data-search-kind]').forEach(enhanceSearchSelect);

const pricing=document.getElementById('item-pricing-form');
function updatePricing(){
 if(!pricing)return;const qty=Number(pricing.elements.quantity.value)||0;
 for(const key of ['supplier_price','kms_price','cooperative_price','kitchen_price']){const target=document.querySelector('[data-preview="'+key+'"]');if(target)target.textContent=money(qty*(Number(pricing.elements[key].value)||0));}
 document.getElementById('kitchen-margin').textContent=money(qty*((Number(pricing.elements.kitchen_price.value)||0)-(Number(pricing.elements.cooperative_price.value)||0)));
}
let offerController;
async function loadOffers(){
 if(!pricing)return;const panel=document.getElementById('supplier-offers');
 if(offerController)offerController.abort();offerController=new AbortController();panel.replaceChildren();
 if(!pricing.elements.product.value){panel.textContent='Cari dan pilih barang untuk melihat penawaran supplier.';return;}
 panel.textContent='Memuat harga…';
 try{
  const url=new URL(pricing.dataset.offersUrl,window.location.origin);url.searchParams.set('product',pricing.elements.product.value);
  const response=await fetch(url,{signal:offerController.signal});if(!response.ok)throw new Error('Offers failed');const data=await response.json();panel.replaceChildren();
  if(!data.offers.length){panel.textContent='Belum ada penawaran. Tambahkan historis atau pilih supplier dan isi harga beli secara manual.';return;}
  data.offers.forEach((quote,index)=>{
   const card=document.createElement('div');card.className='offer-card';
   const title=document.createElement('strong');title.textContent=quote.supplier+(index===0?' · Harga terendah':'');
   const detail=document.createElement('small');detail.textContent=money(Number(quote.price))+'/'+quote.unit+' · Berlaku '+quote.date;
   const button=document.createElement('button');button.type='button';button.className='button';button.textContent='Gunakan supplier ini';
   button.addEventListener('click',()=>{pricing.elements.supplier.add(new Option(quote.supplier,quote.supplier_id,true,true));pricing.elements.supplier.dispatchEvent(new Event('change',{bubbles:true}));pricing.elements.supplier_price.value=quote.price;pricing.elements.supplier_quote.value=quote.id;updatePricing();panel.querySelectorAll('button').forEach(b=>b.textContent='Gunakan supplier ini');button.textContent='✓ Supplier dipilih';});
   card.append(title,detail,button);panel.append(card);
  });
 }catch(error){if(error.name!=='AbortError')panel.textContent='Gagal memuat harga. Coba muat ulang penawaran.';}
}
if(pricing){
 pricing.addEventListener('input',event=>{if(event.target.name==='supplier_price')pricing.elements.supplier_quote.value='';if(event.target.dataset.calc)updatePricing();});
 pricing.addEventListener('change',event=>{
  if(event.target.name==='supplier')pricing.elements.supplier_quote.value='';
  if(event.target.name==='product'){pricing.elements.supplier_quote.value='';pricing.elements.supplier.value='';pricing.elements.supplier_price.value='';const input=document.getElementById('id_supplier_search');if(input)input.value='';loadOffers();updatePricing();}
 });
 const previous=document.getElementById('previous-stage'),next=document.getElementById('next-stage'),save=document.getElementById('save-item');
 pricing.noValidate=true;
 function showStage(stage){pricing.querySelectorAll('[data-stage]').forEach(panel=>panel.hidden=Number(panel.dataset.stage)!==stage);previous.hidden=stage===1;next.hidden=stage===2;save.hidden=stage===1;document.getElementById('goods-step').classList.toggle('current',stage===1);document.getElementById('prices-step').classList.toggle('current',stage===2);}
 previous.addEventListener('click',()=>showStage(1));
 next.addEventListener('click',()=>{const invalid=[...pricing.querySelectorAll('[data-stage="1"] input,[data-stage="1"] select')].find(field=>!field.checkValidity());if(invalid){invalid.reportValidity();return;}showStage(2);});
 pricing.addEventListener('submit',event=>{const invalid=[...pricing.elements].find(field=>typeof field.checkValidity==='function'&&!field.checkValidity());if(invalid){event.preventDefault();showStage(Number(invalid.closest('[data-stage]')?.dataset.stage)||1);invalid.reportValidity();}});
 const error=pricing.querySelector('.errorlist');showStage(error?.closest('[data-stage]')?.dataset.stage==='2'?2:1);
 updatePricing();loadOffers();
 document.getElementById('refresh-offers').addEventListener('click',loadOffers);
}

const proofDialog=document.getElementById('proof-dialog');
let previewSerial=0;
document.addEventListener('click',async event=>{
 const link=event.target.closest('[data-proof-preview]');if(!link||!proofDialog?.showModal)return;
 event.preventDefault();const serial=++previewSerial;const viewer=document.getElementById('proof-viewer');viewer.textContent='Memuat bukti…';document.getElementById('proof-dialog-title').textContent=link.dataset.fileName||'Pratinjau bukti';proofDialog.showModal();
 const url=new URL(link.href);const download=new URL(link.href);download.search='';document.getElementById('proof-download').href=download.href;
 try{const response=await fetch(url,{method:'HEAD'});if(!response.ok)throw new Error('Preview failed');if(serial!==previewSerial||!proofDialog.open)return;const pdf=response.headers.get('Content-Type')?.includes('application/pdf');const content=document.createElement(pdf?'iframe':'img');if(pdf){content.title='Bukti pembayaran PDF';}else content.alt=link.dataset.fileName||'Bukti pembayaran';content.src=url.href;viewer.replaceChildren(content);}catch{viewer.textContent='Pratinjau tidak dapat dibuka. Silakan unduh bukti atau masuk kembali.';}
});
document.querySelector('[data-close-proof]')?.addEventListener('click',()=>proofDialog.close());
proofDialog?.addEventListener('close',()=>{previewSerial++;document.getElementById('proof-viewer').replaceChildren();});

const design=document.getElementById('invoice-design-form');
if(design){
 function refresh(){document.querySelectorAll('[data-design]').forEach(target=>{const key=target.dataset.design;target.textContent=design.elements[key]?.value||(key==='heading'?'Nama organisasi':'');});}
 design.addEventListener('input',refresh);refresh();
 for(const slot of ['left','right']){
  const input=design.elements['logo_'+slot];let objectUrl;
  input.addEventListener('change',()=>{if(design.elements['clear_logo_'+slot])design.elements['clear_logo_'+slot].checked=false;const img=document.getElementById('preview-logo-'+slot);if(objectUrl)URL.revokeObjectURL(objectUrl);if(input.files[0]){objectUrl=URL.createObjectURL(input.files[0]);img.src=objectUrl;img.hidden=false;}});
  design.elements['clear_logo_'+slot]?.addEventListener('change',event=>{document.getElementById('preview-logo-'+slot).hidden=event.target.checked;});
 }
}


const purchaseForm=document.getElementById('bulk-purchase-form');
if(purchaseForm){
 const rows=document.getElementById('purchase-rows'),totalForms=purchaseForm.querySelector('[name="items-TOTAL_FORMS"]');
 const field=(row,key)=>row.querySelector('[name$="-'+key+'"]');
 function refreshPurchaseTotals(){let total=0;rows.querySelectorAll('[data-purchase-row]').forEach(row=>{const deleted=field(row,'DELETE').checked;row.hidden=deleted;if(deleted)return;const value=(Number(field(row,'quantity').value)||0)*(Number(field(row,'supplier_price').value)||0);row.querySelector('[data-row-total]').textContent=money(value);total+=value;});document.getElementById('bulk-purchase-total').textContent=money(total);}
 document.getElementById('add-purchase-row').addEventListener('click',()=>{const index=Number(totalForms.value);if(index>=200){window.alert('Maksimal 200 baris per pengadaan.');return;}const fragment=document.getElementById('purchase-empty-row').innerHTML.replaceAll('__prefix__',String(index));rows.insertAdjacentHTML('beforeend',fragment);totalForms.value=index+1;const row=rows.lastElementChild;row.querySelectorAll('select[data-search-kind]').forEach(enhanceSearchSelect);refreshPurchaseTotals();row.querySelector('input[type="search"]')?.focus();});
 rows.addEventListener('input',event=>{const row=event.target.closest('[data-purchase-row]');if(!row)return;if(event.target.name.endsWith('-supplier_price'))field(row,'supplier_quote').value='';refreshPurchaseTotals();});
 rows.addEventListener('change',event=>{const row=event.target.closest('[data-purchase-row]');if(!row)return;if(event.target.name.endsWith('-product')){field(row,'supplier_quote').value='';field(row,'supplier_price').value='';}if(event.target.name.endsWith('-supplier'))field(row,'supplier_quote').value='';refreshPurchaseTotals();});
 const picker=document.getElementById('supplier-picker'),list=document.getElementById('supplier-picker-list');let pickerSerial=0;
 rows.addEventListener('click',async event=>{
  const row=event.target.closest('[data-purchase-row]');if(!row)return;
  if(event.target.closest('[data-remove-row]')){field(row,'DELETE').checked=true;refreshPurchaseTotals();return;}
  if(!event.target.closest('[data-row-offers]'))return;
  const product=field(row,'product').value;if(!product){window.alert('Cari dan pilih barang terlebih dahulu.');return;}
  const serial=++pickerSerial;list.textContent='Memuat penawaran…';picker.showModal();
  try{const url=new URL(purchaseForm.dataset.offersUrl,window.location.origin);url.searchParams.set('product',product);const response=await fetch(url);if(!response.ok)throw new Error('Offers failed');const data=await response.json();if(serial!==pickerSerial||!picker.open)return;list.replaceChildren();if(!data.offers.length){list.textContent='Belum ada penawaran. Pilih supplier dan isi harga beli secara manual, atau tambahkan historis harga.';return;}
   data.offers.forEach((quote,index)=>{const card=document.createElement('div');card.className='offer-card';const title=document.createElement('strong');title.textContent=quote.supplier+(index===0?' · Harga terendah':'');const detail=document.createElement('p');detail.textContent=money(Number(quote.price))+'/'+quote.unit+' · '+quote.date;const choose=document.createElement('button');choose.type='button';choose.className='button primary';choose.textContent='Gunakan penawaran';choose.addEventListener('click',()=>{const select=field(row,'supplier');select.add(new Option(quote.supplier,quote.supplier_id,true,true));select.dispatchEvent(new Event('change',{bubbles:true}));field(row,'supplier_price').value=quote.price;field(row,'supplier_quote').value=quote.id;picker.close();refreshPurchaseTotals();});card.append(title,detail,choose);list.append(card);});
  }catch{if(serial===pickerSerial)list.textContent='Penawaran tidak dapat dimuat. Tutup lalu coba kembali.';}
 });
 document.getElementById('close-supplier-picker').addEventListener('click',()=>picker.close());picker.addEventListener('close',()=>{pickerSerial++;});refreshPurchaseTotals();
}
const salesForm=document.getElementById('bulk-sales-form');
if(salesForm){function refreshSalesTotals(){for(const key of ['kms_price','cooperative_price','kitchen_price']){let total=0;salesForm.querySelectorAll('[data-sales-row]').forEach(row=>{total+=(Number(row.dataset.quantity)||0)*(Number(row.querySelector('[name$="-'+key+'"]').value)||0);});salesForm.querySelector('[data-sales-total="'+key+'"]').textContent=money(total);}}salesForm.addEventListener('input',refreshSalesTotals);refreshSalesTotals();}

// Shared compact row actions stay outside the table to avoid clipped menus.
const rowDialog=document.getElementById('row-action-dialog');
let rowDialogTrigger;
document.addEventListener('click',event=>{
 const toggle=event.target.closest('[data-toggle-filters]');
 if(toggle){const area=document.getElementById(toggle.getAttribute('aria-controls'));if(area){area.hidden=!area.hidden;toggle.setAttribute('aria-expanded',String(!area.hidden));}return;}
 const trigger=event.target.closest('[data-row-dialog]');
 if(trigger&&rowDialog){const source=document.getElementById(trigger.dataset.rowDialog);if(!source)return;rowDialogTrigger=trigger;document.getElementById('row-action-title').textContent=trigger.dataset.dialogTitle||'Aksi transaksi';document.getElementById('row-action-content').replaceChildren(source.content.cloneNode(true));rowDialog.showModal();}
});
document.querySelector('[data-close-row-dialog]')?.addEventListener('click',()=>rowDialog.close());
rowDialog?.addEventListener('close',()=>{document.getElementById('row-action-content').replaceChildren();rowDialogTrigger?.focus();});

// Selecting another month applies it immediately and leaves all-period mode.
document.querySelectorAll('.transaction-filter-form input[name="month"]').forEach(input=>{
 input.addEventListener('change',()=>{if(!input.value||!input.validity.valid)return;const form=input.form;const all=form.elements['all_months'];if(all)all.checked=false;form.requestSubmit();});
});
