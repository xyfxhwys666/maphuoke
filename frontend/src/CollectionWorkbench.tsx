import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  CircleStop,
  ExternalLink,
  LoaderCircle,
  MapPinned,
  Pause,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Send,
  Workflow,
} from 'lucide-react';
import {
  createCollectionTask,
  cancelCollectionTask,
  deliverCollectionLead,
  deliverCollectionResults,
  getCollectionTask,
  listCollectionTasks,
  openAmapBrowser,
  pauseCollectionTask,
  retryCollectionTaskErrors,
  resumeCollectionTask,
  startCollectionTask,
} from './api';
import { DEFAULT_ERP_DELIVERY_URL } from './config';
import {
  collectionProgressPercent,
  collectionStatusLabel,
  type StatusLabel,
} from './labels';
import type {
  CollectionTask,
  LeadRecord,
} from './types';

export const DEFAULT_COLLECTION_REQUEST = '我是做家具的，寻找全国三线及以上城市的全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。';

const SHENZHEN_RESIDENTIAL_REQUEST = '我想在深圳找做住宅、私宅、豪宅和别墅项目的全案软装公司、室内设计公司和整装公司，需要手机号。';

export function attentionMessage(errors: string[]): string {
  void errors;
  return '高德浏览器需要人工处理。请在旁边的独立 Chrome 窗口完成登录或安全验证，再点击“继续采集”。';
}

const WORK_UNIT_LABELS: Record<string, StatusLabel> = {
  planned: { text: '待执行', detail: '等待开始', tone: 'neutral' },
  queued: { text: '排队中', detail: '等待浏览器处理', tone: 'muted' },
  running: { text: '搜索中', detail: '正在读取高德结果', tone: 'warning' },
  succeeded: { text: '已完成', detail: '已保存候选', tone: 'success' },
  no_result: { text: '无结果', detail: '该关键词未返回候选', tone: 'muted' },
  skipped_limit: { text: '已限流', detail: '城市已达到数量上限', tone: 'muted' },
  retry_wait: { text: '待重试', detail: '等待再次执行', tone: 'danger' },
  needs_attention: { text: '需处理', detail: '浏览器需要人工操作', tone: 'warning' },
  failed: { text: '失败', detail: '工作单元执行失败', tone: 'danger' },
  paused: { text: '已暂停', detail: '任务已暂停', tone: 'muted' },
};

function workUnitLabel(status: string): StatusLabel {
  return WORK_UNIT_LABELS[status] ?? { text: status, detail: '状态待更新', tone: 'neutral' };
}

function formatCount(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value);
}

export function chinaDate(value: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function dailyDeliveryCount(
  tasks: Array<Pick<CollectionTask, 'results'>>,
  date: string,
): number {
  return tasks.reduce((total, task) => total + task.results.filter((lead) => (
    lead.delivery_status === 'delivered'
      && Boolean(lead.delivery_at)
      && chinaDate(lead.delivery_at as string) === date
  )).length, 0);
}

export function collectionDeliveryHistory(
  tasks: Array<Pick<CollectionTask, 'results'>>,
  limit = 7,
): Array<{ date: string; count: number }> {
  const counts = new Map<string, number>();
  tasks.forEach((task) => task.results.forEach((lead) => {
    if (lead.delivery_status !== 'delivered' || !lead.delivery_at) return;
    const date = chinaDate(lead.delivery_at);
    counts.set(date, (counts.get(date) ?? 0) + 1);
  }));
  return [...counts.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .slice(0, limit)
    .map(([date, count]) => ({ date, count }));
}

export function collectionTargetLabel(
  validCount: number,
  target: number | null,
  sourceExhausted: boolean,
): string {
  const progress = target === null
    ? `有效手机 ${formatCount(validCount)}`
    : `有效手机 ${formatCount(validCount)} / ${formatCount(target)}`;
  return sourceExhausted ? `${progress} · 数据源已耗尽` : progress;
}

export function companyNameSourceLabel(channel: string): string {
  void channel;
  return '高德';
}

export const MOBILE_DELIVERY_NOTE = '仅推送含高德有效手机号的最终记录；座机和 400 电话不计入有效结果。';

export const COLLECTION_RESULT_COLUMNS = [
  '城市',
  '公司',
  '高德手机',
  '地址',
  '公司名来源',
  '高德地图',
  '推送',
] as const;

export function initialDeliveryUrl(): string {
  return DEFAULT_ERP_DELIVERY_URL;
}

export function collectionDeliveryAction(status: string, busy: boolean): { label: string; disabled: boolean } {
  if (busy || status === 'pending' || status === 'sending') return { label: '推送中', disabled: true };
  if (status === 'delivered' || status === 'succeeded' || status === 'duplicate') return { label: '已推送', disabled: true };
  if (status === 'failed') return { label: '重新推送', disabled: false };
  return { label: '人工推送', disabled: false };
}

export function validMobile(value: string | null | undefined): string | null {
  return value && /^1[3-9]\d{9}$/.test(value) ? value : null;
}

export type CollectionQueueAction = 'start' | 'pause' | 'resume' | 'cancel';

export function shouldStartCollectionAfterPlan(continuousMode: boolean): boolean {
  return continuousMode;
}

export function collectionQueueActions(status: string): CollectionQueueAction[] {
  if (status === 'running') return ['pause', 'cancel'];
  if (status === 'paused' || status === 'needs_attention') return ['resume', 'cancel'];
  if (status === 'queued') return ['pause', 'cancel'];
  if (status === 'planned') return ['start', 'cancel'];
  return [];
}

export function sortCollectionTasksByCreatedAt<T extends { created_at: string }>(tasks: T[]): T[] {
  return [...tasks].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
}

export function preferredCollectionTask<T extends { status: string; created_at: string }>(tasks: T[]): T | undefined {
  const priority: Record<string, number> = {
    running: 0,
    queued: 1,
    paused: 2,
    needs_attention: 3,
  };
  return [...tasks].sort((left, right) => {
    const priorityDifference = (priority[left.status] ?? 4) - (priority[right.status] ?? 4);
    return priorityDifference || Date.parse(right.created_at) - Date.parse(left.created_at);
  })[0];
}

export function formatQueueCreatedAt(value: string): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
}

function mergeTask(queue: CollectionTask[], task: CollectionTask): CollectionTask[] {
  return sortCollectionTasksByCreatedAt([task, ...queue.filter((item) => item.id !== task.id)]);
}

export function mergeDeliveredLeads(
  current: LeadRecord[],
  delivered: LeadRecord[],
): LeadRecord[] {
  const updates = new Map(delivered.map((lead) => [lead.id, lead]));
  return current.map((lead) => updates.get(lead.id) ?? lead);
}

export default function CollectionWorkbench() {
  const [requestText, setRequestText] = useState(DEFAULT_COLLECTION_REQUEST);
  const [continuousMode, setContinuousMode] = useState(true);
  const [verifiedAutoDeliver, setVerifiedAutoDeliver] = useState(false);
  const [task, setTask] = useState<CollectionTask | null>(null);
  const [queue, setQueue] = useState<CollectionTask[]>([]);
  const [cityFilter, setCityFilter] = useState('');
  const [deliveryUrl, setDeliveryUrl] = useState(initialDeliveryUrl);
  const [deliveryToken, setDeliveryToken] = useState('');
  const [deliveryMessage, setDeliveryMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<'plan' | 'start' | 'pause' | 'cancel' | 'retry' | 'browser' | 'deliver-all' | `deliver-${string}` | null>(null);
  const [queueActionBusy, setQueueActionBusy] = useState<{ taskId: string; action: CollectionQueueAction } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listCollectionTasks()
      .then((response) => {
        if (!active) return;
        const orderedTasks = sortCollectionTasksByCreatedAt(response.items);
        setQueue(orderedTasks);
        const preferredTask = preferredCollectionTask(orderedTasks);
        if (preferredTask) setTask(preferredTask);
      })
      .catch(() => {
        // The workbench remains usable when an older backend has no queue endpoint.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!task || !['queued', 'running'].includes(task.status)) return undefined;
    let active = true;
    const refresh = () => {
      getCollectionTask(task.id)
        .then((next) => {
          if (!active) return;
          setTask(next);
          setQueue((current) => mergeTask(current, next));
        })
        .catch(() => undefined);
    };
    refresh();
    const timer = window.setInterval(refresh, 900);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [task?.id, task?.status]);

  const status = collectionStatusLabel(task?.status ?? 'planned');
  const progress = task
    ? collectionProgressPercent({
        total: task.summary.total_work_units,
        completed: task.summary.completed_work_units,
        failed: task.work_units.filter((unit) => unit.status === 'failed').length,
      })
    : 0;
  const resultRows = useMemo(() => {
    if (!task) return [];
    const leads = new Map(task.results.map((lead) => [lead.id, lead]));
    return task.candidates.map((candidate) => ({
      candidate,
      lead: leads.get(`lead-${candidate.candidate_id}`),
    })).filter(({ candidate }) => !cityFilter || candidate.city === cityFilter);
  }, [cityFilter, task]);

  const resultCities = useMemo(() => Array.from(new Set(
    task?.candidates.map((candidate) => candidate.city) ?? [],
  )), [task]);
  const todayChinaDate = chinaDate(new Date().toISOString());
  const deliveryHistory = useMemo(() => collectionDeliveryHistory(queue), [queue]);
  const todayDeliveryCount = dailyDeliveryCount(queue, todayChinaDate);

  function updateTask(next: CollectionTask) {
    setTask(next);
    setQueue((current) => mergeTask(current, next));
  }

  function syncQueueTask(next: CollectionTask) {
    setTask((current) => current?.id === next.id ? next : current);
    setQueue((current) => mergeTask(current, next));
  }

  function updateLead(nextLead: LeadRecord) {
    if (!task) return;
    updateTask({
      ...task,
      results: task.results.map((lead) => lead.id === nextLead.id ? nextLead : lead),
    });
  }

  async function handlePlan(event: FormEvent) {
    event.preventDefault();
    if (!requestText.trim()) {
      setError('先写一句你要找的客户需求');
      return;
    }
    setBusy('plan');
    setError(null);
    try {
      const created = await createCollectionTask({
        request_text: requestText.trim(),
        continuous_mode: continuousMode,
        auto_deliver: false,
        verified_auto_deliver: verifiedAutoDeliver,
      });
      const next = shouldStartCollectionAfterPlan(continuousMode)
        ? await startCollectionTask(created.id)
        : created;
      updateTask(next);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '需求解析失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleStart() {
    if (!task) return;
    setBusy('start');
    setError(null);
    try {
      updateTask(await startCollectionTask(task.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '采集启动失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleOpenAmap() {
    setBusy('browser');
    setError(null);
    try {
      await openAmapBrowser();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '高德 Chrome 打开失败');
    } finally {
      setBusy(null);
    }
  }

  async function handlePauseOrResume() {
    if (!task) return;
    setBusy('pause');
    setError(null);
    try {
      const next = task.status === 'paused' || task.status === 'needs_attention'
        ? await resumeCollectionTask(task.id)
        : await pauseCollectionTask(task.id);
      updateTask(next);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '任务状态更新失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleRetry() {
    if (!task) return;
    setBusy('retry');
    setError(null);
    try {
      updateTask(await retryCollectionTaskErrors(task.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '工作单元重试失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    if (!task || !['planned', 'queued', 'running', 'paused', 'needs_attention'].includes(task.status)) return;
    setBusy('cancel');
    setError(null);
    try {
      updateTask(await cancelCollectionTask(task.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '终止任务失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleBatchDelivery() {
    if (!task) return;
    if (!deliveryUrl.trim()) {
      setDeliveryMessage('请填写接收 URL。');
      return;
    }
    setBusy('deliver-all');
    setDeliveryMessage(null);
    try {
      const response = await deliverCollectionResults(task.id, deliveryUrl.trim(), deliveryToken.trim());
      updateTask({
        ...task,
        results: mergeDeliveredLeads(task.results, response.items.map((item) => item.lead)),
      });
      setDeliveryMessage(`已推送 ${response.sent} 条，失败 ${response.failed} 条。`);
    } catch (requestError) {
      setDeliveryMessage(requestError instanceof Error ? requestError.message : '批量推送失败');
    } finally {
      setBusy(null);
    }
  }

  async function handleLeadDelivery(lead: LeadRecord) {
    if (!task || !deliveryUrl.trim()) return;
    setBusy(`deliver-${lead.id}`);
    setDeliveryMessage(null);
    try {
      const response = await deliverCollectionLead(task.id, lead.id, deliveryUrl.trim(), deliveryToken.trim());
      updateLead(response.lead);
    } catch (requestError) {
      setDeliveryMessage(requestError instanceof Error ? requestError.message : '单条推送失败');
    } finally {
      setBusy(null);
    }
  }

  async function openQueuedTask(taskId: string) {
    try {
      updateTask(await getCollectionTask(taskId));
    } catch (requestError) {
      const queued = queue.find((item) => item.id === taskId);
      if (queued) setTask(queued);
      setError(requestError instanceof Error ? requestError.message : '任务读取失败');
    }
  }

  async function handleQueueAction(item: CollectionTask, action: CollectionQueueAction) {
    setQueueActionBusy({ taskId: item.id, action });
    setError(null);
    try {
      const next = action === 'start'
        ? await startCollectionTask(item.id)
        : action === 'pause'
        ? await pauseCollectionTask(item.id)
        : action === 'resume'
          ? await resumeCollectionTask(item.id)
          : await cancelCollectionTask(item.id);
      syncQueueTask(next);
    } catch (requestError) {
      const fallback = action === 'cancel' ? '终止任务失败' : '任务状态更新失败';
      setError(requestError instanceof Error ? requestError.message : fallback);
    } finally {
      setQueueActionBusy(null);
    }
  }

  return (
    <section className="collection-workspace" aria-label="CityProspect 自然语言获客工作台">
      <div className="collection-intro">
        <div>
          <p className="panel-kicker">CITYPROSPECT / NATURAL LANGUAGE</p>
          <h2>一句话，生成一张可执行的客户地图。</h2>
          <p className="collection-intro-copy">自然语言会拆成城市 × 关键词计划，公开网页先确认公司全称，再由高德精确查询地址、电话和 POI。</p>
        </div>
        <div className="collection-browser-note">
          <span className="browser-status-dot" />
          <div><strong>高德网页会话</strong><span>{task?.status === 'needs_attention' ? '需要在独立 Chrome 中处理' : '独立 Chrome 手动登录'}</span></div>
          <button className="button button-quiet" type="button" onClick={handleOpenAmap} disabled={busy !== null} title="在独立 Chrome 中打开高德网页">
            {busy === 'browser' ? <LoaderCircle className="spin" size={15} /> : <ExternalLink size={15} />}查看高德
          </button>
        </div>
      </div>

      <section className="collection-delivery-summary panel" aria-label="每日推送统计">
        <div className="collection-delivery-today">
          <span className="panel-kicker">TODAY'S DELIVERY</span>
          <strong>{formatCount(todayDeliveryCount)}</strong>
          <span>今天已推送</span>
        </div>
        <div className="collection-delivery-history">
          <div className="collection-delivery-history-heading">
            <span className="panel-kicker">DELIVERY HISTORY</span>
            <span>按北京时间统计</span>
          </div>
          {deliveryHistory.length === 0 ? (
            <span className="collection-delivery-history-empty">暂无带推送时间的历史记录</span>
          ) : deliveryHistory.map(({ date, count }) => (
            <div className="collection-delivery-history-item" key={date}>
              <span>{date}</span><strong>{formatCount(count)} 条</strong>
            </div>
          ))}
        </div>
      </section>

      <div className="collection-layout">
        <div className="collection-sidebar">
          <form className="collection-request panel" onSubmit={handlePlan}>
            <div className="collection-panel-heading">
              <div><p className="panel-kicker">SEARCH BRIEF</p><h3>描述你要找的客户</h3></div>
              <Sparkles size={19} className="collection-accent-icon" />
            </div>
            <label className="collection-textarea-label" htmlFor="collection-request">
              <span>自然语言需求</span>
              <textarea
                id="collection-request"
                value={requestText}
                onChange={(event) => setRequestText(event.target.value)}
                placeholder="例如：找深圳和广州做高端家装、别墅设计的公司，需要手机号和邮箱，每个城市最多 20 家"
                rows={6}
              />
            </label>
            <div className="collection-example-row" aria-label="需求示例">
              {[
                ['家具商找全国软装客户', DEFAULT_COLLECTION_REQUEST],
                ['深圳住宅软装客户', SHENZHEN_RESIDENTIAL_REQUEST],
              ].map(([label, value]) => (
                <button className="example-chip" type="button" key={label} onClick={() => setRequestText(value)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="collection-toggle-list">
              <label className="collection-toggle">
                <input type="checkbox" checked={continuousMode} onChange={(event) => setContinuousMode(event.target.checked)} />
                <span className="toggle-visual" /><span><strong>持续采集</strong><small>按计划执行完所有城市</small></span>
              </label>
              <label className="collection-toggle">
                <input type="checkbox" checked={verifiedAutoDeliver} onChange={(event) => setVerifiedAutoDeliver(event.target.checked)} />
                <span className="toggle-visual" /><span><strong>自动投递 ERP</strong><small>只投递有独立证据的联系方式</small></span>
              </label>
            </div>

            <button className="button button-primary collection-plan-button" type="submit" disabled={busy !== null}>
              {busy === 'plan' ? <LoaderCircle className="spin" size={17} /> : <Search size={17} />}
              生成采集计划
            </button>
          </form>

          <section className="collection-queue panel" aria-label="采集任务队列">
            <div className="collection-panel-heading">
              <div><p className="panel-kicker">TASK QUEUE</p><h3>任务队列</h3></div>
              <span className="count-badge">{queue.length}</span>
            </div>
            {queue.length === 0 ? (
              <div className="collection-empty-queue"><Workflow size={21} /><span>生成计划后出现在这里</span></div>
            ) : (
              <div className="collection-queue-list">
                {queue.map((item) => {
                  const itemStatus = collectionStatusLabel(item.status);
                  const itemActions = collectionQueueActions(item.status);
                  return (
                    <div className={`collection-queue-item ${item.id === task?.id ? 'is-active' : ''}`} key={item.id}>
                      <button className="collection-queue-select" type="button" onClick={() => openQueuedTask(item.id)}>
                        <span className="queue-item-dot" />
                        <span><strong>{item.name}</strong><small>{itemStatus.text} · 创建：{formatQueueCreatedAt(item.created_at)} · {item.summary.candidate_count} 个候选</small></span>
                      </button>
                      {itemActions.length > 0 && (
                        <div className="collection-queue-actions">
                          {itemActions.map((action) => {
                            const actionBusy = queueActionBusy?.taskId === item.id && queueActionBusy.action === action;
                            const label = action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '终止';
                            const icon = actionBusy
                              ? <LoaderCircle className="spin" size={13} />
                              : action === 'pause'
                                ? <Pause size={13} />
                                : action === 'resume'
                                  ? <Play size={13} />
                                  : <CircleStop size={13} />;
                            const displayedIcon = action === 'start' ? <Play size={13} /> : icon;
                            return (
                              <button
                                className={`collection-queue-action ${action === 'cancel' ? 'is-danger' : ''}`}
                                type="button"
                                key={action}
                                onClick={() => handleQueueAction(item, action)}
                                disabled={busy !== null || queueActionBusy !== null}
                                title={`${label}：${item.name}`}
                              >
                                {displayedIcon}{action === 'start' ? '\u5f00\u59cb' : label}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <div className="collection-main">
          <section className="collection-overview panel" aria-live="polite">
            <div className="collection-overview-top">
              <div>
                <p className="panel-kicker">EXECUTION PLAN</p>
                <h3>{task ? task.name : '等待一条自然语言需求'}</h3>
                <p className="collection-query-line">{task?.request_text || '计划会在这里显示城市范围、关键词和执行规模'}</p>
              </div>
              <div className="collection-action-row">
                {task && ['queued', 'running', 'paused', 'needs_attention'].includes(task.status) && (
                  <button className="button button-quiet" type="button" onClick={handlePauseOrResume} disabled={busy !== null}>
                    {busy === 'pause' ? <LoaderCircle className="spin" size={15} /> : task.status === 'paused' || task.status === 'needs_attention' ? <Play size={15} /> : <Pause size={15} />}
                    {task.status === 'paused' || task.status === 'needs_attention' ? '继续采集' : '暂停'}
                  </button>
                )}
                {task && ['planned', 'queued', 'running', 'paused', 'needs_attention'].includes(task.status) && (
                  <button className="button button-quiet" type="button" onClick={handleCancel} disabled={busy !== null}>
                    {busy === 'cancel' ? <LoaderCircle className="spin" size={15} /> : <CircleStop size={15} />}终止
                  </button>
                )}
                {task && task.status === 'planned' && (
                  <button className="button button-primary" type="button" onClick={handleStart} disabled={busy !== null}>
                    {busy === 'start' ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}开始采集
                  </button>
                )}
                {task && task.status === 'completed_with_errors' && (
                  <button className="button button-secondary" type="button" onClick={handleRetry} disabled={busy !== null}>
                    {busy === 'retry' ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}重试失败项
                  </button>
                )}
              </div>
            </div>
            {error && <div className="notice notice-error collection-notice" role="alert"><AlertTriangle size={16} />{error}</div>}
            <div className="collection-status-row">
              <div className="collection-status-copy"><span className="status-kicker">STATUS</span><span className={`status-pill status-${status.tone}`}>{status.text}</span><span>{status.detail}</span></div>
              <div className="collection-progress-copy"><strong>{progress}%</strong><span>{task ? `${task.summary.completed_work_units} / ${task.summary.total_work_units} 个工作单元` : '尚未生成计划'}</span></div>
            </div>
            <div className="collection-progress-large"><span style={{ width: `${progress}%` }} /></div>
            {task?.status === 'needs_attention' && (
              <div className="collection-attention"><AlertTriangle size={17} /><span>{attentionMessage(task.errors)}</span></div>
            )}
          </section>

          {!task ? (
            <section className="collection-empty-plan panel"><MapPinned size={29} /><strong>执行计划将在这里展开</strong><span>先输入需求并生成计划，系统不会在生成计划时启动地图搜索。</span></section>
          ) : (
            <>
              <section className="collection-stats" aria-label="采集统计">
                {[
                  ['城市', task.plan.city_count, task.plan.city_scope_label],
                  ['关键词', task.plan.keywords.length, '已去重'],
                  ['公司名', task.company_name_candidates.length, '公开网页确认'],
                  ['匹配', task.summary.relevant_count, '高德精确查询'],
                  ['联系方式', task.summary.contact_count, '满足需求字段'],
                  ['已核验', task.summary.verified_count, '独立证据状态'],
                ].map(([label, value, detail]) => (
                  <div className="collection-stat" key={String(label)}><span>{label}</span><strong>{formatCount(Number(value))}</strong><small>{detail}</small></div>
                ))}
              </section>

              <section className="collection-delivery panel">
                <div className="collection-panel-heading">
                  <div><p className="panel-kicker">ERP DELIVERY</p><h3>推送到另一个系统 API</h3></div>
                  <button className="button button-dark" type="button" onClick={handleBatchDelivery} disabled={busy !== null || !deliveryUrl.trim() || task.results.every((lead) => !validMobile(lead.mobile))}>
                    {busy === 'deliver-all' ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}批量推送
                  </button>
                </div>
                <div className="collection-delivery-fields">
                  <label>接收 URL<input value={deliveryUrl} onChange={(event) => setDeliveryUrl(event.target.value)} placeholder="https://your-system.example/api/leads" /></label>
                  <label>Bearer Token（可选）<input type="password" value={deliveryToken} onChange={(event) => setDeliveryToken(event.target.value)} /></label>
                </div>
                <p className="collection-delivery-note">{MOBILE_DELIVERY_NOTE}</p>
                {deliveryMessage && <p className="collection-delivery-message">{deliveryMessage}</p>}
              </section>

            </>
          )}
        </div>
      </div>

      <section className="collection-results panel" aria-label="采集结果">
        <div className="collection-panel-heading collection-results-heading">
          <div><p className="panel-kicker">COLLECTION RESULTS</p><h3>采集结果</h3></div>
          <div className="collection-results-tools">
            <span className="collection-plan-meta">{resultRows.length} 条高德最终结果</span>
            <span className="collection-target-meta">
              {collectionTargetLabel(
                task?.summary.valid_contact_count ?? 0,
                task?.summary.target_valid_contacts ?? task?.intent.target_valid_contacts ?? null,
                task?.summary.source_exhausted ?? false,
              )}
            </span>
            {task && <span className="collection-plan-meta">无有效手机 {task.summary.no_phone_count} · 拒绝 {task.summary.rejected_count}</span>}
            <select aria-label="按城市筛选" value={cityFilter} onChange={(event) => setCityFilter(event.target.value)}><option value="">全部城市</option>{resultCities.map((city) => <option key={city}>{city}</option>)}</select>
          </div>
        </div>
        <div className="collection-table-wrap">
          <table className="collection-table">
            <thead><tr>{COLLECTION_RESULT_COLUMNS.map((column) => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {resultRows.length === 0 ? (
                <tr><td className="collection-table-empty" colSpan={COLLECTION_RESULT_COLUMNS.length}><Search size={18} />高德精确匹配后，最终公司记录会出现在这里</td></tr>
              ) : resultRows.map(({ candidate, lead }) => {
                const deliveryStatus = lead?.delivery_status || 'display_only';
                const nameDiscoveryChannel = String(candidate.source_metadata['discovery_channel'] || 'public_web');
                const nameSourceLabel = companyNameSourceLabel(nameDiscoveryChannel);
                const phone = validMobile(candidate.mobile) || validMobile(lead?.mobile);
                const hasPhone = Boolean(phone);
                const rowBusy = busy === `deliver-${lead?.id}`;
                const deliveryAction = collectionDeliveryAction(deliveryStatus, rowBusy);
                const deliveryTitle = !deliveryUrl.trim()
                  ? '请先填写接收 URL'
                  : !hasPhone
                    ? '该高德结果没有有效手机号'
                    : deliveryStatus === 'failed'
                      ? '上次推送失败，点击重新推送'
                      : undefined;
                return (
                  <tr key={candidate.candidate_id}>
                    <td>{candidate.city}</td>
                    <td><strong>{candidate.company_name}</strong><small>{candidate.poi_id ? `POI ${candidate.poi_id}` : '高德 POI'}</small></td>
                    <td className="mono">{phone || '未公开'}</td>
                    <td>{candidate.address || lead?.address || '未公开'}</td>
                    <td>{nameSourceLabel}</td>
                    <td>{candidate.source_url ? <a className="collection-source-link" href={candidate.source_url} target="_blank" rel="noreferrer" title="打开高德结果"><ExternalLink size={13} />打开高德</a> : '未公开'}</td>
                    <td><button className={`collection-row-delivery ${deliveryAction.label === '已推送' ? 'is-delivered' : deliveryStatus === 'failed' ? 'is-retry' : ''}`} type="button" title={deliveryTitle} onClick={() => lead && handleLeadDelivery(lead)} disabled={!lead || !hasPhone || !deliveryUrl.trim() || busy !== null || deliveryAction.disabled}><Send size={13} />{deliveryAction.label}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
