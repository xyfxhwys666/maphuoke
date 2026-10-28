import { useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  ExternalLink,
  FileSearch,
  FileSpreadsheet,
  LoaderCircle,
  MapPin,
  Pause,
  Phone,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  SquareArrowOutUpRight,
  Upload,
} from 'lucide-react';
import {
  createBatch,
  createTask,
  deliverTask,
  enrichTask,
  getBatch,
  getTask,
  pauseBatch,
  pauseTask,
  retryBatchErrors,
  retryTaskErrors,
  resumeTask,
  resumeBatch,
  startTask,
  startBatch,
  verifyTask,
} from './api';
import CollectionWorkbench from './CollectionWorkbench';
import { batchItemLabel, batchLabel, deliveryLabel, evidenceStatus, shouldRetryDelivery, taskLabel, type StatusLabel } from './labels';
import type { BatchJob, DeliveryResult, LeadRecord, MapPoiCandidate, SearchTask } from './types';

type BusyAction = 'search' | 'enrich' | 'deliver' | 'retry' | 'pause' | 'batch' | 'batch-retry' | 'batch-pause' | 'open-task' | null;
type WorkspaceMode = 'collection' | 'single' | 'batch';

export const NATURAL_LANGUAGE_HERO_COPY = '输入自然语言需求，公开网页先确认真实公司全称，再由高德网页逐家公司精确查询。';

const contactOptions = [
  { value: 'mobile', label: '手机号' },
  { value: 'email', label: '邮箱' },
  { value: 'wechat', label: '微信' },
];

function ValueRow({ label, value, icon }: { label: string; value: string | null | undefined; icon: React.ReactNode }) {
  return (
    <div className="value-row">
      <span className="value-icon" aria-hidden="true">{icon}</span>
      <span className="value-label">{label}</span>
      <strong className={value ? '' : 'is-empty'}>{value || '暂无'}</strong>
    </div>
  );
}

function StatusPill({ label }: { label: StatusLabel }) {
  return <span className={`status-pill status-${label.tone}`}>{label.text}</span>;
}

function EvidenceTag({ status }: { status: string }) {
  const label = status === 'verified' ? '已核验' : status === 'source_backed' ? '有来源' : '已捕获';
  return <span className={`evidence-tag evidence-${status}`}>{status === 'verified' && <Check size={12} />}{label}</span>;
}

function sourceLabel(channel: string) {
  return channel === 'amap_web' ? '高德网页' : channel === 'amap_api' ? '高德 API' : '地图候选';
}

export default function App() {
  const [companyName, setCompanyName] = useState('');
  const [city, setCity] = useState('深圳市');
  const [requiredContacts, setRequiredContacts] = useState(['mobile', 'email', 'wechat']);
  const [autoDeliver, setAutoDeliver] = useState(false);
  const [task, setTask] = useState<SearchTask | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [delivery, setDelivery] = useState<DeliveryResult | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<WorkspaceMode>('collection');
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<BatchJob | null>(null);

  const selectedCandidate = useMemo<MapPoiCandidate | null>(
    () => task?.candidates.find((candidate) => candidate.candidate_id === selectedId) ?? null,
    [selectedId, task],
  );
  const selectedLead = useMemo<LeadRecord | null>(
    () => task?.leads.find((lead) => lead.id === `lead-${selectedId}`) ?? null,
    [selectedId, task],
  );
  const evidenceUrls = selectedLead
    ? Array.from(new Set([...selectedLead.source_urls, ...selectedLead.contact_evidence_urls]))
    : selectedCandidate?.source_urls ?? [];
  const evidenceQuotes = selectedLead
    ? Array.from(new Set([...selectedLead.contact_evidence_quotes, ...selectedLead.evidence_quotes]))
    : [];
  const status = taskLabel(task?.status ?? 'created');
  const deliveryState = deliveryLabel(delivery?.status ?? selectedLead?.delivery_status ?? 'display_only', delivery?.reasons ?? []);
  const failedBatchCount = batch?.items.filter((item) => item.status === 'failed').length ?? 0;
  const completedBatchCount = batch?.items.filter((item) => item.status === 'completed').length ?? 0;
  const currentBatchLabel = batchLabel(batch?.status ?? 'created', failedBatchCount, batch?.total ?? 0);
  const retryingDelivery = shouldRetryDelivery(task?.status ?? '', delivery?.status ?? selectedLead?.delivery_status);

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (!companyName.trim() || !city.trim()) {
      setError('请输入公司名称和城市');
      return;
    }
    if (!requiredContacts.length) {
      setError('至少选择一种需要补全的联系方式');
      return;
    }
    setBusy('search');
    setError(null);
    setDelivery(null);
    try {
      const created = await createTask({
        company_name: companyName.trim(),
        city: city.trim(),
        required_contacts: requiredContacts,
        auto_deliver: autoDeliver,
      });
      const started = await startTask(created.id);
      setTask(started);
      setSelectedId(started.candidates[0]?.candidate_id ?? null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '地图搜索失败');
    } finally {
      setBusy(null);
    }
  }

  function toggleContact(value: string) {
    setRequiredContacts((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  }

  async function pollBatch(batchId: string, initial: BatchJob) {
    let latest = initial;
    for (let attempt = 0; attempt < 120 && latest.status === 'running'; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
      latest = await getBatch(batchId);
      setBatch(latest);
    }
    return latest;
  }

  async function handleBatchSubmit(event: FormEvent) {
    event.preventDefault();
    if (!batchFile) {
      setError('请选择 CSV 或 XLSX 文件');
      return;
    }
    setBusy('batch');
    setError(null);
    try {
      const created = await createBatch(batchFile);
      setBatch(created);
      const started = await startBatch(created.id);
      setBatch(started);
      if (started.status === 'running') {
        await pollBatch(started.id, started);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '批量导入失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleBatchRetry() {
    if (!batch) return;
    setBusy('batch-retry');
    setError(null);
    try {
      const retried = await retryBatchErrors(batch.id);
      setBatch(retried);
      if (retried.status === 'running') {
        await pollBatch(retried.id, retried);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '批量重试失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleBatchPause() {
    if (!batch) return;
    setBusy('batch-pause');
    setError(null);
    try {
      const updated = batch.status === 'paused' ? await resumeBatch(batch.id) : await pauseBatch(batch.id);
      setBatch(updated);
      if (updated.status === 'running') {
        await pollBatch(updated.id, updated);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '批量状态更新失败');
    } finally {
      setBusy(null);
    }
  }

  function handleBatchFileChange(event: ChangeEvent<HTMLInputElement>) {
    setBatchFile(event.target.files?.[0] ?? null);
    setError(null);
  }

  async function handleOpenTask(taskId: string) {
    setBusy('open-task');
    setError(null);
    try {
      const opened = await getTask(taskId);
      setTask(opened);
      setSelectedId(opened.candidates[0]?.candidate_id ?? null);
      setDelivery(null);
      setMode('single');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '打开子任务失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleEnrich() {
    if (!task || !selectedId) return;
    setBusy('enrich');
    setError(null);
    try {
      const enriched = await enrichTask(task.id, selectedId);
      const enrichedLead = enriched.leads.find((lead) => lead.id === `lead-${selectedId}`);
      if (!enrichedLead || enriched.status === 'waiting_for_login' || enriched.status === 'waiting_for_challenge') {
        setTask(enriched);
        return;
      }
      const verified = await verifyTask(task.id, selectedId);
      setTask(verified ?? enriched);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '豆包补全失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleDeliver() {
    if (!task || !selectedId) return;
    setBusy('deliver');
    setError(null);
    try {
      const result = await deliverTask(task.id, selectedId);
      setTask(result.task);
      setDelivery(result.delivery);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '推送失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleRetryDelivery() {
    if (!task) return;
    setBusy('retry');
    setError(null);
    try {
      setTask(await retryTaskErrors(task.id));
      setDelivery(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '投递重试失败');
    } finally {
      setBusy(null);
    }
  }

  async function handlePause() {
    if (!task) return;
    setBusy('pause');
    setError(null);
    try {
      setTask(task.status === 'paused' ? await resumeTask(task.id) : await pauseTask(task.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '任务状态更新失败');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark"><MapPin size={19} strokeWidth={2.4} /></span>
          <span className="brand-name">map / lead</span>
          <span className="brand-divider" />
          <span className="brand-context">线索工作台</span>
        </div>
        <div className="topbar-meta"><span className="live-dot" />本地工作区</div>
      </header>

      <main className="workspace">
        <section className="search-hero" aria-labelledby="page-title">
          <div>
            <p className="eyebrow">CITYPROSPECT / 01</p>
            <h1 id="page-title">一句话，找到下一批客户。</h1>
            <p className="hero-copy">{NATURAL_LANGUAGE_HERO_COPY}</p>
          </div>
          <div className="hero-index" aria-hidden="true">01<span>/</span>04</div>
        </section>

        <div className="mode-tabs" role="tablist" aria-label="查询模式">
          <button className={`mode-tab ${mode === 'collection' ? 'is-active' : ''}`} type="button" role="tab" aria-selected={mode === 'collection'} onClick={() => setMode('collection')}>
            <Sparkles size={16} />自然语言获客
          </button>
          <button className={`mode-tab ${mode === 'single' ? 'is-active' : ''}`} type="button" role="tab" aria-selected={mode === 'single'} onClick={() => setMode('single')}>
            <Search size={16} />单家公司
          </button>
          <button className={`mode-tab ${mode === 'batch' ? 'is-active' : ''}`} type="button" role="tab" aria-selected={mode === 'batch'} onClick={() => setMode('batch')}>
            <FileSpreadsheet size={16} />批量导入
          </button>
        </div>

        {mode === 'collection' ? null : mode === 'single' ? (
          <form className="search-form" onSubmit={handleSearch}>
            <label className="field field-company">
              <span>公司名称</span>
              <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="例如：深圳示例科技有限公司" />
            </label>
            <label className="field field-city">
              <span>城市</span>
              <input value={city} onChange={(event) => setCity(event.target.value)} placeholder="例如：深圳市" />
            </label>
            <fieldset className="field-options">
              <legend>需要补全</legend>
              <div className="option-row">
                {contactOptions.map((option) => (
                  <label className="check-option" key={option.value}>
                    <input type="checkbox" checked={requiredContacts.includes(option.value)} onChange={() => toggleContact(option.value)} />
                    <span>{option.label}</span>
                  </label>
                ))}
                <label className="check-option check-option-auto">
                  <input type="checkbox" checked={autoDeliver} onChange={(event) => setAutoDeliver(event.target.checked)} />
                  <span>核验通过后自动推送 ERP</span>
                </label>
              </div>
            </fieldset>
            <button className="button button-primary search-button" type="submit" disabled={busy !== null}>
              {busy === 'search' ? <LoaderCircle className="spin" size={18} /> : <Search size={18} />}
              地图搜索
            </button>
          </form>
        ) : (
          <form className="batch-form panel" onSubmit={handleBatchSubmit}>
            <div className="batch-form-copy">
              <p className="panel-kicker">BATCH DISCOVERY / 05</p>
              <h2>一次导入多家公司</h2>
              <p>每行需要公司名称和城市。系统会顺序搜索高德地图，失败项可单独重试。</p>
            </div>
            <div className="batch-form-actions">
              <label className="file-choice" htmlFor="batch-file">
                <FileSpreadsheet size={18} />
                <span>{batchFile?.name || '选择 CSV 或 XLSX'}</span>
                <input id="batch-file" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={handleBatchFileChange} />
              </label>
              <button className="button button-primary" type="submit" disabled={busy !== null || !batchFile}>
                {busy === 'batch' ? <LoaderCircle className="spin" size={18} /> : <Upload size={18} />}
                上传并开始
              </button>
            </div>
          </form>
        )}

        {error && <div className="notice notice-error" role="alert"><CircleAlert size={17} />{error}</div>}

        {mode === 'collection' ? <CollectionWorkbench /> : mode === 'single' ? <>
          <section className="status-line" aria-live="polite">
            <div className="status-summary"><span className="status-kicker">TASK STATUS</span><StatusPill label={status} /><span>{status.detail}</span></div>
            {task && <button className="button button-quiet" type="button" onClick={handlePause} disabled={busy !== null}>
              {busy === 'pause' ? <LoaderCircle className="spin" size={16} /> : task.status === 'paused' ? <Play size={16} /> : <Pause size={16} />}
              {task.status === 'paused' ? '恢复' : '暂停'}
            </button>}
          </section>

          <section className="workbench-grid" aria-label="企业候选与线索详情">
          <aside className="candidate-panel panel">
            <div className="panel-heading">
              <div><p className="panel-kicker">MAP RESULTS</p><h2>候选 POI</h2></div>
              <span className="count-badge">{task?.candidates.length ?? 0}</span>
            </div>
            {!task?.candidates.length ? (
              <div className="empty-state"><FileSearch size={22} /><strong>还没有候选企业</strong><span>输入公司和城市开始地图搜索</span></div>
            ) : (
              <div className="candidate-list">
                {task.candidates.map((candidate, index) => (
                  <button
                    className={`candidate-item ${candidate.candidate_id === selectedId ? 'is-selected' : ''}`}
                    key={candidate.candidate_id}
                    type="button"
                    aria-pressed={candidate.candidate_id === selectedId}
                    onClick={() => { setSelectedId(candidate.candidate_id); setDelivery(null); }}
                  >
                    <span className="candidate-number">{String(index + 1).padStart(2, '0')}</span>
                    <span className="candidate-body">
                      <strong>{candidate.company_name}</strong>
                      <span>{candidate.address || '地址未提供'}</span>
                      <span className="candidate-meta"><span>{candidate.category || '企业服务'}</span><span>{sourceLabel(candidate.discovery_channel)}</span></span>
                    </span>
                    <ArrowUpRight className="candidate-arrow" size={17} />
                  </button>
                ))}
              </div>
            )}
            <div className="panel-footnote"><span className="footnote-mark" />候选不会因为缺少手机号而被丢弃</div>
          </aside>

          <section className="detail-panel panel">
            {!selectedCandidate ? (
              <div className="detail-empty"><span className="coordinate-icon"><MapPin size={26} /></span><h2>选择一个候选企业</h2><p>地图结果会保留原始地址、电话和来源，确认后再交给豆包补全。</p></div>
            ) : (
              <>
                <div className="detail-heading">
                  <div>
                    <p className="panel-kicker">SELECTED POI / {selectedCandidate.candidate_id}</p>
                    <h2>{selectedCandidate.company_name}</h2>
                    <p className="detail-subtitle">{selectedCandidate.city} · {selectedCandidate.category || '企业服务'}</p>
                  </div>
                  {selectedCandidate.source_url && <a className="icon-link" href={selectedCandidate.source_url} target="_blank" rel="noreferrer" aria-label="打开地图来源" title="打开地图来源"><ExternalLink size={19} /></a>}
                </div>

                <div className="source-strip"><span className="source-strip-icon"><MapPin size={15} /></span><span>{sourceLabel(selectedCandidate.discovery_channel)}</span><span className="source-divider" /><span className="mono">{selectedCandidate.poi_id || selectedCandidate.candidate_id}</span><span className="source-spacer" /><span className="captured-label" title={selectedCandidate.evidence_snapshot_id || undefined}>快照 {selectedCandidate.evidence_snapshot_id || '未生成'}</span></div>

                <div className="value-grid">
                  <ValueRow label="地址" value={selectedCandidate.address} icon={<MapPin size={16} />} />
                  <ValueRow label="地图电话" value={selectedCandidate.telephone} icon={<Phone size={16} />} />
                  <ValueRow label="分类" value={selectedCandidate.category} icon={<FileSearch size={16} />} />
                  <ValueRow label="坐标" value={selectedCandidate.longitude && selectedCandidate.latitude ? `${selectedCandidate.longitude}, ${selectedCandidate.latitude}` : null} icon={<MapPin size={16} />} />
                </div>

                <div className="enrichment-section">
                  <div className="section-heading"><div><p className="panel-kicker">PUBLIC CONTACTS / 02</p><h3>联系方式补全</h3></div><ShieldCheck size={20} className="section-icon" /></div>
                  <div className="enrichment-action-row"><p>{selectedLead ? '结果已保存，可查看来源和证据状态。' : '只查询这家公司，不使用名称或常识推测联系人。'}</p><button className="button button-secondary" type="button" onClick={handleEnrich} disabled={busy !== null || task?.status === 'paused'}>{busy === 'enrich' ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{selectedLead ? '重新补全' : '豆包补全'}</button></div>
                </div>

                <div className="lead-section">
                  <div className="section-heading"><div><p className="panel-kicker">LEAD RECORD / 03</p><h3>统一线索</h3></div>{selectedLead && <EvidenceTag status={evidenceStatus(undefined, selectedLead.contact_verification_status)} />}</div>
                  <div className="lead-table-wrap">
                    <table className="lead-table"><thead><tr><th>字段</th><th>内容</th><th>来源 / 状态</th></tr></thead><tbody>
                      <tr><td>手机号</td><td className="mono">{selectedLead?.mobile || '暂无'}</td><td><span className="table-source">{selectedLead ? sourceLabel(selectedLead.discovery_channel) : '等待补全'}</span>{selectedLead && <EvidenceTag status={evidenceStatus(selectedLead.field_evidence.mobile?.status, selectedLead.contact_verification_status)} />}</td></tr>
                      <tr><td>联系人</td><td>{selectedLead?.contact_person_name || '暂无'}</td><td>{selectedLead?.contact_person_role || '未发现职务'}</td></tr>
                      <tr><td>邮箱</td><td className="mono">{selectedLead?.email || '暂无'}</td><td>{selectedLead?.source_urls.length ? '公开来源' : '等待补全'}</td></tr>
                      <tr><td>微信</td><td className="mono">{selectedLead?.wechat || '暂无'}</td><td>{selectedLead?.wechat ? '豆包返回' : '等待补全'}</td></tr>
                      <tr><td>服务简介</td><td colSpan={2}>{selectedLead?.service_intro || selectedCandidate.category || '暂无'}</td></tr>
                    </tbody></table>
                  </div>
                </div>

                <div className="evidence-detail">
                  <div className="section-heading"><div><p className="panel-kicker">EVIDENCE / 03A</p><h3>来源与证据</h3></div><ShieldCheck size={20} className="section-icon" /></div>
                  {evidenceUrls.length ? (
                    <div className="evidence-links">
                      {evidenceUrls.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer"><ExternalLink size={13} />{url}</a>)}
                    </div>
                  ) : <p className="evidence-empty">暂无可打开的来源链接</p>}
                  {evidenceQuotes.length > 0 && <div className="evidence-quotes">{evidenceQuotes.map((quote) => <blockquote key={quote}>{quote}</blockquote>)}</div>}
                </div>

                <div className="delivery-section">
                  <div><p className="panel-kicker">ERP DELIVERY / 04</p><div className="delivery-title"><StatusPill label={deliveryState} /><span>{deliveryState.detail}</span></div></div>
                  <button className="button button-dark" type="button" onClick={retryingDelivery ? handleRetryDelivery : handleDeliver} disabled={busy !== null || !selectedLead || (!retryingDelivery && task?.status !== 'ready')}>
                    {busy === 'deliver' || busy === 'retry' ? <LoaderCircle className="spin" size={17} /> : retryingDelivery ? <RefreshCw size={17} /> : <SquareArrowOutUpRight size={17} />}
                    {retryingDelivery ? '重试投递' : deliveryState.text === '仅展示' ? '检查门禁' : '推送 ERP'}
                  </button>
                </div>
              </>
            )}
          </section>
          </section>
        </> : (
          <section className="batch-workspace" aria-label="批量地图搜索结果">
            <section className="batch-status-line" aria-live="polite">
              <div className="status-summary"><span className="status-kicker">BATCH STATUS</span><StatusPill label={currentBatchLabel} /><span>{batch ? `${completedBatchCount} / ${batch.total} 家已完成` : '等待上传批量文件'}</span></div>
              {batch && <div className="batch-status-actions">
                {(batch.status === 'running' || batch.status === 'paused') && <button className="button button-quiet" type="button" onClick={handleBatchPause} disabled={busy !== null}>
                  {busy === 'batch-pause' ? <LoaderCircle className="spin" size={16} /> : batch.status === 'paused' ? <Play size={16} /> : <Pause size={16} />}
                  {batch.status === 'paused' ? '恢复批量' : '暂停批量'}
                </button>}
                {failedBatchCount > 0 && <button className="button button-quiet" type="button" onClick={handleBatchRetry} disabled={busy !== null}>
                  {busy === 'batch-retry' ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}
                  重试失败项
                </button>}
              </div>}
            </section>

            {!batch ? (
              <div className="batch-empty panel"><FileSpreadsheet size={24} /><strong>批量结果会显示在这里</strong><span>上传包含“公司名称”和“城市”两列的 CSV 或 XLSX 文件</span></div>
            ) : (
              <section className="batch-results panel">
                <div className="panel-heading">
                  <div><p className="panel-kicker">BATCH QUEUE</p><h2>{batch.filename}</h2></div>
                  <span className="count-badge">{batch.total}</span>
                </div>
                <div className="batch-table-wrap">
                  <table className="batch-table"><thead><tr><th>#</th><th>公司</th><th>状态</th><th>候选</th><th>子任务</th></tr></thead><tbody>
                    {batch.items.map((item, index) => {
                      const itemStatus = batchItemLabel(item.status);
                      return <tr key={item.item_id}>
                        <td className="batch-seq">{String(index + 1).padStart(2, '0')}</td>
                        <td><strong>{item.company_name}</strong><span className="batch-secondary">{item.city} · 第 {item.row_number} 行</span></td>
                        <td><StatusPill label={itemStatus} />{item.error && <span className="batch-error">{item.error}</span>}</td>
                        <td className="mono">{item.candidate_count || '—'}</td>
                        <td>{item.task_id ? <button className="button button-quiet batch-open" type="button" onClick={() => handleOpenTask(item.task_id!)} disabled={busy !== null} title="打开单家公司工作台"><ArrowUpRight size={15} />打开</button> : '—'}</td>
                      </tr>;
                    })}
                  </tbody></table>
                </div>
              </section>
            )}
          </section>
        )}
      </main>
      <footer className="app-footer"><span>Map Lead Platform</span><span>证据优先 · 自动推送默认关闭</span></footer>
    </div>
  );
}
