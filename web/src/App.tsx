import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ProxySettings, type StatusData } from './api'
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
} from './icons'

type Section = 'overview' | 'credentials' | 'settings'
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

  const loadStatus = useCallback(async (silent = false) => {
    try {
      const data = await api.status()
      setStatus(data)
      setSettings((current) => current ?? data.settings)
    } catch (error) {
      if (!silent) setNotice({ tone: 'error', message: errorMessage(error) })
    }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void loadStatus(), 0)
    const timer = window.setInterval(() => void loadStatus(true), 5000)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [loadStatus])

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
          <NavItem active={section === 'credentials'} icon={<KeyIcon />} label="OAuth 凭证" onClick={() => setSection('credentials')} />
          <NavItem active={section === 'settings'} icon={<SlidersIcon />} label="代理设置" onClick={() => setSection('settings')} />
        </nav>
        <div className="sidebar-foot">
          <ShieldIcon />
          <div><strong>仅监听本机</strong><span>凭证不会离开你的设备</span></div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL CODEX GATEWAY</p>
            <h1>{sectionTitle(section)}</h1>
          </div>
          <div className="service-pill"><i /> 服务运行中 <span>127.0.0.1</span></div>
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
  const rate = status.service.request_count ? Math.round((status.service.success_count / status.service.request_count) * 100) : 100
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

      <section className="metrics-grid">
        <Metric label="代理请求" value={String(status.service.request_count)} detail="本次运行累计" />
        <Metric label="成功率" value={`${rate}%`} detail={`${status.service.success_count} 次成功`} />
        <Metric label="最近状态" value={status.service.last_status ? `HTTP ${status.service.last_status}` : '等待请求'} detail={status.service.last_request_at ? formatDate(status.service.last_request_at) : '尚无转发记录'} />
      </section>

      <section className="card access-card">
        <div className="card-heading"><div><span className="icon-box"><GaugeIcon /></span><div><h3>接入 Codex</h3><p>将下面两项写入 Codex 客户端配置</p></div></div><span className="protocol-tag">Responses API</span></div>
        <FieldCopy label="Base URL" value={status.endpoint} onCopy={() => onCopy(status.endpoint, 'Base URL 已复制')} />
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
      <div className="settings-footer"><p>服务始终只监听 127.0.0.1，不开放局域网访问。</p><button className="primary-button" onClick={onSave} disabled={busy === 'save-settings'}>{busy === 'save-settings' ? '保存中…' : '保存设置'}</button></div>
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

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
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
  return section === 'overview' ? '运行概览' : section === 'credentials' ? 'OAuth 凭证' : '代理设置'
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
