# Loads the Sisyphus Stream Deck config into Companion with no clicks.
#
#   powershell -ExecutionPolicy Bypass -File import-config.ps1          # back up, merge main, import, verify
#   powershell -ExecutionPolicy Bypass -File import-config.ps1 -DryRun  # same, but stop before importing
#
# It replaces only the buttons. Connections, surfaces, custom variables (govee_key) and
# user settings stay as they are, so the deck never disconnects and no secret is rewritten.
# Importing does not press any key. Roll back with -File <a companion-backup-*.companionconfig>.
param(
    [switch]$DryRun,
    [string]$File,
    [string]$Ref = 'main',
    [string]$Companion = 'http://192.168.86.42:8000'
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$node = Get-ChildItem "$env:ProgramFiles\Companion\resources\node-runtimes\*\node.exe" | Sort-Object FullName | Select-Object -Last 1
if (-not $node) { throw 'Companion node runtime not found' }

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$dl = "$env:USERPROFILE\Downloads"
$backup = "$dl\companion-backup-$stamp.companionconfig"
$merged = "$dl\sisyphus-deck-merged-$stamp.companionconfig"
$work = Join-Path $env:TEMP "companion-import-$stamp"
New-Item -ItemType Directory -Force $work | Out-Null

$live = Invoke-WebRequest -UseBasicParsing "$Companion/int/export/full?format=json" -TimeoutSec 30
[IO.File]::WriteAllBytes($backup, $live.Content)
"Backup: $backup"

$deck = $File
if (-not $deck) {
    $deck = "$work\repo-deck.companionconfig"
    Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/companion/sisyphus-deck.companionconfig" -OutFile $deck -TimeoutSec 30
}

$js = @'
const fs = require('fs'), crypto = require('crypto')
const [backupPath, deckPath, mergedPath, url, dryRun] = process.argv.slice(2)
const read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'))
const fail = (m) => { console.error('FAILED: ' + m); process.exit(1) }

// Merge: live config with the deck's pages, mapping deck connection labels to live ids.
function merge(current, deckText) {
	const idByLabel = {}
	for (const [id, inst] of Object.entries(current.instances)) idByLabel[inst.label] = id
	for (const [key, inst] of Object.entries(JSON.parse(deckText).instances || {})) {
		const liveId = idByLabel[inst.label]
		if (!liveId) fail(`no live connection labelled ${inst.label}`)
		deckText = deckText.replace(new RegExp(`"connectionId"(\\s*):(\\s*)"${key}"`, 'g'), `"connectionId":"${liveId}"`)
	}
	const deck = JSON.parse(deckText)
	const merged = { ...current, pages: deck.pages, custom_variables: { ...current.custom_variables } }
	for (const [name, v] of Object.entries(deck.custom_variables || {})) {
		if (!merged.custom_variables[name]) merged.custom_variables[name] = v
	}
	return merged
}

// What a button does, ignoring style and ids, so layered and plain buttons compare equal.
const strip = (a) => ({ def: a.definitionId, conn: a.connectionId, opt: a.options, kids: Object.values(a.children || {}).map((l) => l.map(strip)) })
function behaviour(cfg) {
	const out = {}
	for (const [n, pg] of Object.entries(cfg.pages))
		for (const [r, row] of Object.entries(pg.controls || {}))
			for (const [c, b] of Object.entries(row || {})) {
				const sets = {}
				for (const [s, step] of Object.entries(b.steps || {}))
					for (const [k, acts] of Object.entries(step.action_sets || {})) if (acts && acts.length) sets[`${s}.${k}`] = acts.map(strip)
				out[`${n}/${r}/${c}`] = JSON.stringify(sets)
			}
	return out
}
const diffKeys = (a, b) => [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => (a[k] || '{}') !== (b[k] || '{}'))

// tRPC over websocket. pendingImport lives on the socket, so everything uses one connection.
function connect() {
	const ws = new WebSocket(url.replace(/^http/, 'ws') + '/trpc')
	let nextId = 1
	const waiting = new Map(), subs = new Map()
	ws.onmessage = (e) => {
		if (e.data === 'PING') return ws.send('PONG')
		const m = JSON.parse(e.data)
		if (m.error && waiting.has(m.id)) { waiting.get(m.id).reject(new Error(m.error.message)); waiting.delete(m.id); return }
		if (subs.has(m.id)) { if (m.result && m.result.type !== 'started' && m.result.type !== 'stopped') subs.get(m.id)(m.result.data); return }
		if (waiting.has(m.id)) { waiting.get(m.id).resolve(m.result ? m.result.data : undefined); waiting.delete(m.id) }
	}
	const call = (method, path, input) => new Promise((resolve, reject) => {
		const id = nextId++
		waiting.set(id, { resolve, reject })
		ws.send(JSON.stringify({ id, jsonrpc: '2.0', method, params: { path, input } }))
	})
	const subscribe = (path, input, fn) => {
		const id = nextId++
		subs.set(id, fn)
		ws.send(JSON.stringify({ id, jsonrpc: '2.0', method: 'subscription', params: { path, input } }))
		return () => { subs.delete(id); ws.send(JSON.stringify({ id, jsonrpc: '2.0', method: 'subscription.stop' })) }
	}
	return new Promise((resolve, reject) => {
		ws.onopen = () => resolve({ ws, mutate: (p, i) => call('mutation', p, i), query: (p, i) => call('query', p, i), subscribe })
		ws.onerror = () => reject(new Error('websocket failed'))
	})
}

const firstValue = (rpc, path) => new Promise((resolve, reject) => {
	const t = setTimeout(() => reject(new Error('no data from ' + path)), 5000)
	const stop = rpc.subscribe(path, undefined, (d) => { clearTimeout(t); stop(); resolve(d) })
})

async function deckStatus(rpc) {
	const data = await firstValue(rpc, 'surfaces.watchSurfaces')
	return Object.values(data[0].info).flatMap((g) => g.surfaces || []).map((s) => `${s.type} ${s.isConnected ? 'connected' : 'OFFLINE'}`)
}

async function main() {
	const live = read(backupPath)
	const merged = merge(live, fs.readFileSync(deckPath, 'utf8'))
	const text = JSON.stringify(merged)
	fs.writeFileSync(mergedPath, text)

	const before = behaviour(live), wanted = behaviour(merged)
	const changes = diffKeys(before, wanted)
	console.log('Buttons changing: ' + (changes.join(' ') || 'none'))

	const rpc = await connect()
	console.log('Surfaces: ' + (await deckStatus(rpc)).join(', '))

	const bytes = Buffer.from(text)
	const sessionId = await rpc.mutate('importExport.prepareImport.start', { name: 'deck.companionconfig', size: bytes.length })
	for (let offset = 0; offset < bytes.length; offset += 512 * 1024) {
		const data = bytes.subarray(offset, offset + 512 * 1024).toString('base64')
		await rpc.mutate('importExport.prepareImport.uploadChunk', { sessionId, offset, data })
	}
	const sha1 = crypto.createHash('sha1').update(bytes).digest('hex')
	const res = await rpc.mutate('importExport.prepareImport.complete', { sessionId, expectedChecksum: sha1, userData: null })
	const [err, info] = Array.isArray(res) ? res : [null, res]
	if (err) fail('Companion rejected the file: ' + err)
	console.log(`Companion parsed it: type ${info.type}, ${Object.keys(info.pages || {}).length} pages`)

	if (dryRun === 'true') {
		await rpc.mutate('importExport.abort')
		console.log('Dry run: nothing imported.')
		rpc.ws.close()
		return
	}

	let task
	const stop = rpc.subscribe('importExport.importExportTaskStatus', undefined, (d) => { task = d })
	const { runId } = await rpc.mutate('importExport.importFull', { config: {
		buttons: 'reset-and-import',
		surfaces: { known: 'unchanged', instances: 'unchanged', remote: 'unchanged' },
		triggers: 'unchanged', customVariables: 'unchanged', expressionVariables: 'unchanged',
		connections: 'unchanged', userconfig: 'unchanged', imageLibrary: 'unchanged',
	} })
	const start = Date.now()
	while (!(task && task.runId === runId && task.status === 'completed')) {
		if (Date.now() - start > 60000) fail('import did not finish within 60s')
		await new Promise((r) => setTimeout(r, 250))
	}
	stop()
	if (task.error) fail('import error: ' + task.error)
	await new Promise((r) => setTimeout(r, 3000))

	// Verify against a fresh export.
	const after = await (await fetch(url + '/int/export/full?format=json')).json()
	const off = diffKeys(behaviour(after), wanted)
	if (off.length) fail('buttons do not match after import: ' + off.join(' '))
	if (Object.keys(after.pages).length !== Object.keys(merged.pages).length) fail('page count changed')
	for (const name of Object.keys(live.custom_variables)) {
		if (JSON.stringify(after.custom_variables[name]) !== JSON.stringify(live.custom_variables[name])) fail(`custom variable ${name} changed`)
	}
	const conns = (j) => Object.keys(j.instances).sort().join()
	if (conns(after) !== conns(live)) fail('connections changed')
	console.log(`Verified: ${Object.keys(wanted).length} buttons match, custom variables and connections unchanged`)
	console.log('Surfaces: ' + (await deckStatus(rpc)).join(', '))
	const health = (await firstValue(rpc, 'instances.statuses.watch')).statuses
	const bad = Object.keys(live.instances).filter((id) => live.instances[id].enabled !== false && health[id] && health[id].category !== 'good')
	console.log('Connections not healthy: ' + (bad.map((id) => live.instances[id].label).join(', ') || 'none'))
	rpc.ws.close()
}
main().then(() => process.exit(0), (e) => fail(e.stack || e.message))
'@
$jsPath = "$work\import.js"
[IO.File]::WriteAllText($jsPath, $js, (New-Object Text.UTF8Encoding($false)))

& $node.FullName $jsPath $backup $deck $merged $Companion ([string][bool]$DryRun).ToLower()
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"Merged file: $merged"
