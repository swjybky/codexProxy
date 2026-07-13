import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ManagedKey, type ProxySettings, type StatusData, type UsageData, type UsageRange } from './api'
import {
  BoltIcon,
  CheckIcon,
  CloseIcon,
  CopyIcon,
  EyeIcon,
  GaugeIcon,
  KeyIcon,
  RefreshIcon,
  ShieldIcon,
  SlidersIcon,
  TokenIcon,
} from './icons'

type Section = 'overview' | 'keys' | 'usage' | 'credentials' | 'settings'
type Notice = { tone: 'success' | 'error'; message: string } | null

function App() {
  const [section, setSection] = useState<Section>('overview')
  const [status, setStatus] = useState<StatusData | null>(null)
  const [settings, setSettings] = useState<ProxySettings | null>(null)
  const [notice, setNotice] = useState<Notice>(null)
  const [busy, setBusy] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [credentialJson, setCredentialJson] = useState('')
  const [usageRange, setUsageRange] = useState<UsageRange>('24h')
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageKey, setUsageKey] = useState('all')
  const [usageVersion, setUsageVersion] = useState(0)
  const [managedKeys, setManagedKeys] = useState<ManagedKey[]>([])
  const [keysLoading, setKeysLoading] = useState(false)

  const loadStatus = useCallback(async (silent = false) => {
    try {
      const data = await api.status()
      setStatus(data)
      setSettings((current) => current ?? data.settings)
    } catch (error) {
      if (!silent) setNotice({ tone: 'error', message: errorMessage(error) })
    }
  }, [])

  const loadKeys = useCallback(async (silent = false) => {
    if (!silent) setKeysLoading(true)
    try {
      const data = await api.keys()
      setManagedKeys(data.keys)
    } catch (error) {
      if (!silent) setNotice({ tone: 'error', message: errorMessage(error) })
    } finally {
      if (!silent) setKeysLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void loadStatus(), 0)
    const timer = window.setInterval(() => void loadStatus(true), 30000)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [loadStatus])

  useEffect(() => {
    if (section !== 'usage') return
    let active = true
    const initial = window.setTimeout(() => {
      setUsageLoading(true)
      api.usage(usageRange, usageKey)
        .then((data) => { if (active) setUsage(data) })
        .catch((error) => { if (active) setNotice({ tone: 'error', message: errorMessage(error) }) })
        .finally(() => { if (active) setUsageLoading(false) })
    }, 0)
    return () => {
      active = false
      window.clearTimeout(initial)
    }
  }, [section, usageRange, usageKey, usageVersion])

  useEffect(() => {
    if (section !== 'keys' && section !== 'usage') return
    const initial = window.setTimeout(() => void loadKeys(), 0)
    return () => window.clearTimeout(initial)
  }, [section, loadKeys])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 4200)
    return () => window.clearTimeout(timer)
  }, [notice])

  const run = async (name: string, operation: () => Promise<unknown>, success: string) => {
    setBusy(name)
    try {
      await operation()
      await loadStatus(true)
      setNotice({ tone: 'success', message: success })
    } catch (error) {
      setNotice({ tone: 'error', message: errorMessage(error) })
    } finally {
      setBusy('')
    }
  }

  const saveSettings = async () => {
    if (!settings) return
    await run('save-settings', () => api.saveSettings(settings), '设置已保存，新请求会立即使用')
  }

  const importJson = async () => {
    await run('import-json', () => api.importCredentials(credentialJson), 'OAuth 凭证已安全导入')
    setShowImport(false)
    setCredentialJson('')
  }

  const copy = async (value: string, message: string) => {
    await navigator.clipboard.writeText(value)
    setNotice({ tone: 'success', message })
  }

  const createManagedKey = async (name: string, tokenLimit: number) => {
    setBusy('create-key')
    try {
      const data = await api.createKey(name, tokenLimit)
      setManagedKeys((current) => [...current, data.key])
      setNotice({ tone: 'success', message: `秘钥“${data.key.name}”已创建` })
      return true
    } catch (error) {
      setNotice({ tone: 'error', message: errorMessage(error) })
      return false
    } finally {
      setBusy('')
    }
  }

  const resetManagedKey = async (key: ManagedKey) => {
    if (!window.confirm(`确认重置“${key.name}”的 Token 用量吗？`)) return
    setBusy(`reset-${key.id}`)
    try {
      const data = await api.resetKeyUsage(key.id)
      setManagedKeys((current) => current.map((item) => item.id === key.id ? data.key : item))
      setUsageVersion((value) => value + 1)
      setNotice({ tone: 'success', message: `“${key.name}”的用量已重置` })
    } catch (error) {
      setNotice({ tone: 'error', message: errorMessage(error) })
    } finally {
      setBusy('')
    }
  }

  const deleteManagedKey = async (key: ManagedKey) => {
    if (!window.confirm(`确认删除秘钥“${key.name}”吗？删除后将立即无法使用。`)) return
    setBusy(`delete-${key.id}`)
    try {
      await api.deleteKey(key.id)
      setManagedKeys((current) => current.filter((item) => item.id !== key.id))
      if (usageKey === key.id) setUsageKey('all')
      setUsageVersion((value) => value + 1)
      setNotice({ tone: 'success', message: `秘钥“${key.name}”已删除` })
    } catch (error) {
      setNotice({ tone: 'error', message: errorMessage(error) })
    } finally {
      setBusy('')
    }
  }

  const maskedKey = useMemo(() => {
    const key = status?.local_api_key ?? ''
    return showKey ? key : key.replace(/.(?=.{6})/g, '•')
  }, [showKey, status?.local_api_key])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><BoltIcon /></div>
          <div><strong>Codex Proxy</strong><span>Desktop relay</span></div>
        </div>
        <nav>
          <NavItem active={section === 'overview'} icon={<GaugeIcon />} label="运行概览" onClick={() => setSection('overview')} />
          <NavItem active={section === 'keys'} icon={<KeyIcon />} label="秘钥管理" onClick={() => setSection('keys')} />
          <NavItem active={section === 'usage'} icon={<TokenIcon />} label="Token 统计" onClick={() => setSection('usage')} />
          <NavItem active={section === 'credentials'} icon={<KeyIcon />} label="OAuth 凭证" onClick={() => setSection('credentials')} />
          <NavItem active={section === 'settings'} icon={<SlidersIcon />} label="代理设置" onClick={() => setSection('settings')} />
        </nav>
        <div className="sidebar-foot">
          <ShieldIcon />
          <div><strong>API Key 保护</strong><span>局域网请求也必须鉴权</span></div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL CODEX GATEWAY</p>
            <h1>{sectionTitle(section)}</h1>
          </div>
          <div className="service-pill"><i /> 服务运行中 <span>本机 + 局域网</span></div>
        </header>

        {!status ? <LoadingState /> : (
          <div className="content">
            {section === 'overview' && (
              <Overview
                status={status}
                maskedKey={maskedKey}
                showKey={showKey}
                onShowKey={() => setShowKey((value) => !value)}
                onCopy={copy}
                busy={busy}
                onTest={() => run('test', () => api.testConnection(status.settings.default_model), '上游连接正常')}
              />
            )}
            {section === 'usage' && (
              <Usage
                usage={usage}
                range={usageRange}
                loading={usageLoading}
                keys={managedKeys}
                selectedKey={usageKey}
                onRangeChange={setUsageRange}
                onKeyChange={setUsageKey}
              />
            )}
            {section === 'keys' && (
              <KeyManagement
                keys={managedKeys}
                loading={keysLoading}
                busy={busy}
                onCreate={createManagedKey}
                onCopy={copy}
                onReset={resetManagedKey}
                onDelete={deleteManagedKey}
              />
            )}
            {section === 'credentials' && (
              <Credentials
                status={status}
                busy={busy}
                onImportDefault={() => run('import-default', api.importDefaultCredentials, '已从 Codex CLI 导入凭证')}
                onOpenImport={() => setShowImport(true)}
                onRefresh={() => run('refresh', api.refreshCredentials, 'OAuth 凭证刷新成功')}
              />
            )}
            {section === 'settings' && settings && (
              <Settings settings={settings} setSettings={setSettings} busy={busy} onSave={saveSettings} />
            )}
          </div>
        )}
      </main>

      {notice && <div className={`toast ${notice.tone}`} role="status" aria-live="polite"><span>{notice.tone === 'success' ? <CheckIcon /> : <CloseIcon />}</span>{notice.message}</div>}
      {showImport && (
        <ImportDialog
          value={credentialJson}
          onChange={setCredentialJson}
          onClose={() => setShowImport(false)}
          onImport={importJson}
          busy={busy === 'import-json'}
        />
      )}
    </div>
  )
}

function KeyManagement({ keys, loading, busy, onCreate, onCopy, onReset, onDelete }: {
  keys: ManagedKey[]
  loading: boolean
  busy: string
  onCreate: (name: string, tokenLimit: number) => Promise<boolean>
  onCopy: (value: string, message: string) => void
  onReset: (key: ManagedKey) => void
  onDelete: (key: ManagedKey) => void
}) {
  const [name, setName] = useState('')
  const [tokenLimit, setTokenLimit] = useState(5_000_000)
  const quotaOptions = [
    { value: 5_000_000, label: '500 万 Token' },
    { value: 10_000_000, label: '1000 万 Token' },
    { value: 20_000_000, label: '2000 万 Token' },
    { value: 100_000_000, label: '1 亿 Token' },
  ]
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    if (await onCreate(name.trim(), tokenLimit)) setName('')
  }
  return (
    <>
      <section className="card key-create-card">
        <div className="card-heading">
          <div><span className="icon-box"><KeyIcon /></span><div><h3>新建用户秘钥</h3><p>名称会用于 Token 统计筛选，创建后可复制给其他用户</p></div></div>
          <span className="protocol-tag">管理员 Key 不限额</span>
        </div>
        <form className="key-create-form" onSubmit={submit}>
          <label className="form-field"><span>秘钥名称（必填）</span><input value={name} maxLength={60} onChange={(event) => setName(event.target.value)} placeholder="例如：张三 / 测试团队" /></label>
          <label className="form-field"><span>Token 额度</span><select value={tokenLimit} onChange={(event) => setTokenLimit(Number(event.target.value))}>{quotaOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <button className="primary-button" type="submit" disabled={!name.trim() || busy === 'create-key'}>{busy === 'create-key' ? '正在创建…' : '创建秘钥'}</button>
        </form>
      </section>

      <section className="key-list-heading"><div><h2>用户秘钥</h2><p>达到额度后，请求会被暂停，重置用量后即可恢复</p></div><span>{keys.length} 个</span></section>
      {loading && !keys.length ? <div className="key-empty"><i />正在加载秘钥…</div> : keys.length ? (
        <section className="key-list">
          {keys.map((key) => {
            const percent = Math.min(100, key.token_limit ? key.used_tokens / key.token_limit * 100 : 0)
            return (
              <article className="card managed-key" key={key.id}>
                <div className="managed-key-head"><div><span className="managed-key-icon"><KeyIcon /></span><div><h3>{key.name}</h3><p>创建于 {formatDate(key.created_at)}</p></div></div><span className={percent >= 100 ? 'quota-badge exhausted' : 'quota-badge'}>{formatQuota(key.token_limit)}</span></div>
                <div className="managed-key-value"><code>{maskManagedKey(key.key)}</code><button className="copy-button" onClick={() => onCopy(key.key, `“${key.name}”秘钥已复制`)}><CopyIcon />复制</button></div>
                <div className="quota-row"><div><span>已使用 {formatTokens(key.used_tokens)}</span><strong>{percent.toFixed(percent >= 10 ? 0 : 1)}%</strong></div><div className="quota-track"><i style={{ width: `${percent}%` }} /></div><small>剩余 {key.remaining_tokens.toLocaleString('zh-CN')} Token</small></div>
                <div className="managed-key-actions"><button className="secondary-button" disabled={busy === `reset-${key.id}` || key.used_tokens === 0} onClick={() => onReset(key)}><RefreshIcon />{busy === `reset-${key.id}` ? '重置中…' : '重置用量'}</button><button className="danger-button" disabled={busy === `delete-${key.id}`} onClick={() => onDelete(key)}>{busy === `delete-${key.id}` ? '删除中…' : '删除秘钥'}</button></div>
              </article>
            )
          })}
        </section>
      ) : <div className="card key-empty"><KeyIcon /><strong>还没有用户秘钥</strong><span>填写名称并选择额度后即可创建</span></div>}
    </>
  )
}

function Usage({ usage, range, loading, keys, selectedKey, onRangeChange, onKeyChange }: {
  usage: UsageData | null
  range: UsageRange
  loading: boolean
  keys: ManagedKey[]
  selectedKey: string
  onRangeChange: (range: UsageRange) => void
  onKeyChange: (keyId: string) => void
}) {
  const ranges: Array<{ value: UsageRange; label: string }> = [
    { value: '24h', label: '近 24 小时' },
    { value: '7d', label: '近 7 天' },
    { value: '30d', label: '近 30 天' },
    { value: 'all', label: '全部' },
  ]
  const totals = usage?.totals ?? { total_tokens: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0 }
  return (
    <>
      <section className="usage-toolbar">
        <div><h2>Token 消耗</h2><p>仅保存按小时汇总的数据，不记录单次调用内容</p></div>
        <div className="usage-filters">
          <label><span>秘钥筛选</span><select value={selectedKey} onChange={(event) => onKeyChange(event.target.value)}><option value="all">全部秘钥</option><option value="admin">管理员 Key（无限额）</option>{keys.map((key) => <option key={key.id} value={key.id}>{key.name}</option>)}</select></label>
          <div className="range-tabs" aria-label="统计时间范围">
            {ranges.map((item) => <button key={item.value} className={range === item.value ? 'active' : ''} onClick={() => onRangeChange(item.value)}>{item.label}</button>)}
          </div>
        </div>
      </section>
      <section className="usage-metrics">
        <UsageMetric label="总 Token" value={totals.total_tokens} tone="total" />
        <UsageMetric label="输入 Token" value={totals.input_tokens} tone="input" />
        <UsageMetric label="输出 Token" value={totals.output_tokens} tone="output" />
        <UsageMetric label="缓存命中" value={totals.cached_tokens} tone="cached" />
      </section>
      <section className="card usage-chart-card">
        <div className="usage-chart-head">
          <div><h3>使用趋势</h3><p>{usage?.bucket === 'hour' ? '按小时汇总' : '按天汇总'}</p></div>
          <div className="chart-legend"><span className="input">输入</span><span className="output">输出</span><span className="cached">缓存命中</span></div>
        </div>
        {loading && !usage ? <div className="chart-empty"><i />正在加载统计…</div> : <TokenChart data={usage} />}
      </section>
    </>
  )
}

function UsageMetric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`usage-metric ${tone}`}><span>{label}</span><strong>{formatTokens(value)}</strong><small>{value.toLocaleString('zh-CN')} tokens</small></div>
}

function TokenChart({ data }: { data: UsageData | null }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const points = data?.points ?? []
  if (!points.length) return <div className="chart-empty"><TokenIcon /><strong>暂无 Token 数据</strong><span>完成一次代理请求后，汇总数据会显示在这里</span></div>
  const width = 820
  const height = 260
  const left = 54
  const right = 18
  const top = 18
  const bottom = 42
  const chartWidth = width - left - right
  const chartHeight = height - top - bottom
  const maxValue = Math.max(1, ...points.flatMap((point) => [point.input_tokens, point.output_tokens, point.cached_tokens]))
  const x = (index: number) => left + (points.length === 1 ? chartWidth / 2 : index * chartWidth / (points.length - 1))
  const y = (value: number) => top + chartHeight - value / maxValue * chartHeight
  const line = (field: 'input_tokens' | 'output_tokens' | 'cached_tokens') => points.map((point, index) => `${x(index)},${y(point[field])}`).join(' ')
  const labelEvery = Math.max(1, Math.ceil(points.length / 7))
  const activePoint = activeIndex === null ? null : points[activeIndex]
  const activeX = activeIndex === null ? 0 : x(activeIndex)
  const tooltipWidth = 164
  const tooltipHeight = 94
  const tooltipX = activeX + 12 + tooltipWidth <= width - right ? activeX + 12 : activeX - tooltipWidth - 12
  const tooltipY = top + 8
  return (
    <div className="token-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Token 使用趋势图">
        {[0, .25, .5, .75, 1].map((ratio) => {
          const gridY = top + chartHeight * ratio
          return <g key={ratio}><line className="grid-line" x1={left} y1={gridY} x2={width - right} y2={gridY} /><text className="axis-label" x={left - 9} y={gridY + 4} textAnchor="end">{formatTokens(Math.round(maxValue * (1 - ratio)))}</text></g>
        })}
        <polyline className="usage-line input" points={line('input_tokens')} />
        <polyline className="usage-line output" points={line('output_tokens')} />
        <polyline className="usage-line cached" points={line('cached_tokens')} />
        {points.map((point, index) => (
          <g key={point.timestamp}>
            <circle className="usage-dot input" cx={x(index)} cy={y(point.input_tokens)} r="3" />
            <circle className="usage-dot output" cx={x(index)} cy={y(point.output_tokens)} r="3" />
            <circle className="usage-dot cached" cx={x(index)} cy={y(point.cached_tokens)} r="3" />
            {(index % labelEvery === 0 || index === points.length - 1) && <text className="axis-label x" x={x(index)} y={height - 12} textAnchor="middle">{formatUsageDate(point.timestamp, data?.bucket)}</text>}
          </g>
        ))}
        <rect
          className="chart-hit-area"
          x={left}
          y={top}
          width={chartWidth}
          height={chartHeight}
          onPointerMove={(event) => {
            const bounds = event.currentTarget.ownerSVGElement?.getBoundingClientRect()
            if (!bounds) return
            const pointerX = (event.clientX - bounds.left) / bounds.width * width
            const index = points.length === 1
              ? 0
              : Math.round((pointerX - left) / chartWidth * (points.length - 1))
            setActiveIndex(Math.max(0, Math.min(points.length - 1, index)))
          }}
          onPointerLeave={() => setActiveIndex(null)}
        />
        {activePoint && (
          <g className="chart-hover" pointerEvents="none">
            <line className="chart-hover-line" x1={activeX} y1={top} x2={activeX} y2={top + chartHeight} />
            <circle className="chart-hover-dot input" cx={activeX} cy={y(activePoint.input_tokens)} r="5" />
            <circle className="chart-hover-dot output" cx={activeX} cy={y(activePoint.output_tokens)} r="5" />
            <circle className="chart-hover-dot cached" cx={activeX} cy={y(activePoint.cached_tokens)} r="5" />
            <g transform={`translate(${tooltipX} ${tooltipY})`}>
              <rect className="chart-tooltip-bg" width={tooltipWidth} height={tooltipHeight} rx="7" />
              <text className="chart-tooltip-date" x="12" y="18">{formatUsageTooltipDate(activePoint.timestamp, data?.bucket)}</text>
              <circle className="chart-tooltip-marker input" cx="14" cy="36" r="3" />
              <text className="chart-tooltip-label" x="23" y="39">输入 Token</text>
              <text className="chart-tooltip-value" x={tooltipWidth - 12} y="39" textAnchor="end">{activePoint.input_tokens.toLocaleString('zh-CN')}</text>
              <circle className="chart-tooltip-marker output" cx="14" cy="57" r="3" />
              <text className="chart-tooltip-label" x="23" y="60">输出 Token</text>
              <text className="chart-tooltip-value" x={tooltipWidth - 12} y="60" textAnchor="end">{activePoint.output_tokens.toLocaleString('zh-CN')}</text>
              <circle className="chart-tooltip-marker cached" cx="14" cy="78" r="3" />
              <text className="chart-tooltip-label" x="23" y="81">缓存命中</text>
              <text className="chart-tooltip-value" x={tooltipWidth - 12} y="81" textAnchor="end">{activePoint.cached_tokens.toLocaleString('zh-CN')}</text>
            </g>
          </g>
        )}
      </svg>
    </div>
  )
}

function NavItem({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button className={active ? 'nav-item active' : 'nav-item'} onClick={onClick}>{icon}<span>{label}</span></button>
}

function Overview({ status, maskedKey, showKey, onShowKey, onCopy, busy, onTest }: {
  status: StatusData
  maskedKey: string
  showKey: boolean
  onShowKey: () => void
  onCopy: (value: string, message: string) => void
  busy: string
  onTest: () => void
}) {
  return (
    <>
      <section className="hero-card">
        <div className="hero-copy">
          <span className="status-label"><i /> READY</span>
          <h2>Codex 已准备好通过本机转发</h2>
          <p>兼容 OpenAI Responses 协议，自动适配 ChatGPT Codex 订阅后端。</p>
        </div>
        <button className="primary-button" onClick={onTest} disabled={busy === 'test' || !status.credentials.configured}>
          <BoltIcon />{busy === 'test' ? '正在测试…' : '测试上游连接'}
        </button>
      </section>

      <section className="card access-card">
        <div className="card-heading"><div><span className="icon-box"><GaugeIcon /></span><div><h3>接入 Codex</h3><p>选择对应网络的 Base URL，并配置同一个 API Key</p></div></div><span className="protocol-tag">Responses API</span></div>
        <FieldCopy label="本机 Base URL" value={status.endpoint} onCopy={() => onCopy(status.endpoint, '本机 Base URL 已复制')} />
        {status.lan_endpoint && <FieldCopy label="局域网 Base URL" value={status.lan_endpoint} onCopy={() => onCopy(status.lan_endpoint!, '局域网 Base URL 已复制')} />}
        <div className="copy-field">
          <label>API Key</label>
          <div><code>{maskedKey}</code><button className="icon-button" title={showKey ? '隐藏' : '显示'} onClick={onShowKey}><EyeIcon /></button><button className="copy-button" onClick={() => onCopy(status.local_api_key, 'API Key 已复制')}><CopyIcon />复制</button></div>
        </div>
        <div className="endpoint-row"><span><CheckIcon />POST /v1/responses</span><span><CheckIcon />POST /v1/responses/compact</span><span><CheckIcon />SSE 流式响应</span></div>
      </section>
    </>
  )
}

function Credentials({ status, busy, onImportDefault, onOpenImport, onRefresh }: {
  status: StatusData
  busy: string
  onImportDefault: () => void
  onOpenImport: () => void
  onRefresh: () => void
}) {
  const credentials = status.credentials
  return (
    <section className="card credential-card">
      <div className="credential-head">
        <div className={credentials.configured ? 'account-icon configured' : 'account-icon'}><KeyIcon /></div>
        <div><span className={credentials.configured ? 'state-badge good' : 'state-badge'}>{credentials.configured ? '已连接' : '未配置'}</span><h2>{credentials.email || '连接你的 Codex 订阅'}</h2><p>{credentials.configured ? 'OAuth 凭证已存储在本机用户数据目录' : '导入 Codex CLI 登录凭证后即可开始转发'}</p></div>
      </div>
      {credentials.configured && (
        <div className="credential-details">
          <Detail label="Account ID" value={credentials.account_id || '—'} />
          <Detail label="过期时间" value={formatDate(credentials.expired)} />
          <Detail label="最近刷新" value={formatDate(credentials.last_refresh)} />
        </div>
      )}
      <div className="credential-actions">
        <button className="primary-button" onClick={onImportDefault} disabled={Boolean(busy)}><RefreshIcon />{busy === 'import-default' ? '正在导入…' : '从 Codex CLI 导入'}</button>
        <button className="secondary-button" onClick={onOpenImport} disabled={Boolean(busy)}>粘贴 OAuth JSON</button>
        {credentials.configured && <button className="secondary-button" onClick={onRefresh} disabled={Boolean(busy) || !credentials.refreshable}><RefreshIcon />{busy === 'refresh' ? '刷新中…' : '立即刷新'}</button>}
      </div>
      <div className="info-strip"><ShieldIcon /><span><strong>本地安全存储</strong>Access Token 与 Refresh Token 不会展示在界面或写入请求日志；凭证文件权限限制为当前用户。</span></div>
    </section>
  )
}

function Settings({ settings, setSettings, busy, onSave }: {
  settings: ProxySettings
  setSettings: (settings: ProxySettings) => void
  busy: string
  onSave: () => void
}) {
  const update = <K extends keyof ProxySettings>(key: K, value: ProxySettings[K]) => setSettings({ ...settings, [key]: value })
  return (
    <section className="card settings-card">
      <div className="card-heading"><div><span className="icon-box"><SlidersIcon /></span><div><h3>Codex 适配设置</h3><p>变更会作用于后续转发请求</p></div></div></div>
      <div className="form-grid">
        <label className="form-field"><span>上游地址</span><input value={settings.upstream_base_url} onChange={(event) => update('upstream_base_url', event.target.value)} placeholder="https://chatgpt.com" /></label>
        <label className="form-field"><span>默认模型</span><input value={settings.default_model} onChange={(event) => update('default_model', event.target.value)} placeholder="gpt-5.4" /></label>
        <label className="form-field full"><span>网络代理（可选）</span><input value={settings.proxy_url} onChange={(event) => update('proxy_url', event.target.value)} placeholder="http://127.0.0.1:7890" /></label>
        <label className="form-field full"><span>附加 Instructions（可选）</span><textarea value={settings.system_prompt} onChange={(event) => update('system_prompt', event.target.value)} placeholder="为所有请求注入统一的系统提示词" rows={5} /></label>
      </div>
      <label className="switch-row">
        <button type="button" role="switch" aria-checked={settings.system_prompt_override} className={settings.system_prompt_override ? 'switch on' : 'switch'} onClick={() => update('system_prompt_override', !settings.system_prompt_override)}><i /></button>
        <span><strong>合并客户端 Instructions</strong><small>开启后，附加提示词会置于客户端原有 instructions 之前</small></span>
      </label>
      <div className="settings-footer"><p>服务同时监听本机与局域网；所有代理请求均需 API Key。</p><button className="primary-button" onClick={onSave} disabled={busy === 'save-settings'}>{busy === 'save-settings' ? '保存中…' : '保存设置'}</button></div>
    </section>
  )
}

function ImportDialog({ value, onChange, onClose, onImport, busy }: { value: string; onChange: (value: string) => void; onClose: () => void; onImport: () => void; busy: boolean }) {
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <button className="modal-close" aria-label="关闭导入窗口" title="关闭" onClick={onClose}><CloseIcon /></button>
        <span className="modal-icon"><KeyIcon /></span>
        <h2 id="import-title">导入 OAuth 凭证</h2>
        <p>支持 new-api 渠道 Key JSON，也支持 Codex CLI 的 auth.json 完整内容。</p>
        <textarea autoFocus value={value} onChange={(event) => onChange(event.target.value)} rows={10} spellCheck={false} placeholder={'{\n  "access_token": "...",\n  "refresh_token": "...",\n  "account_id": "..."\n}'} />
        <div className="modal-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={!value.trim() || busy} onClick={onImport}>{busy ? '正在导入…' : '安全导入'}</button></div>
      </div>
    </div>
  )
}

function FieldCopy({ label, value, onCopy }: { label: string; value: string; onCopy: () => void }) {
  return <div className="copy-field"><label>{label}</label><div><code>{value}</code><button className="copy-button" onClick={onCopy}><CopyIcon />复制</button></div></div>
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function LoadingState() {
  return <div className="loading-state"><i /><span>正在连接本地服务…</span></div>
}

function sectionTitle(section: Section) {
  if (section === 'overview') return '运行概览'
  if (section === 'keys') return '秘钥管理'
  if (section === 'usage') return 'Token 统计'
  return section === 'credentials' ? 'OAuth 凭证' : '代理设置'
}

function formatTokens(value: number) {
  return new Intl.NumberFormat('zh-CN', { notation: value >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value)
}

function formatQuota(value: number) {
  if (value === 100_000_000) return '1 亿额度'
  return `${value / 10_000} 万额度`
}

function maskManagedKey(value: string) {
  if (value.length <= 18) return value.replace(/.(?=.{5})/g, '•')
  return `${value.slice(0, 10)}${'•'.repeat(12)}${value.slice(-6)}`
}

function formatUsageDate(value: string, bucket?: 'hour' | 'day') {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return bucket === 'hour'
    ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    : date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function formatUsageTooltipDate(value: string, bucket?: 'hour' | 'day') {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return bucket === 'hour'
    ? date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
    : date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function formatDate(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export default App
