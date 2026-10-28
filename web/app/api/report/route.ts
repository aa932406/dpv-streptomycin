import { NextRequest } from 'next/server'

// 报告要现场训练一遍所有模型（10 个），30 秒是常态。
// 走 next.config 的 /api/* 反代时，代理会在 30 秒处把连接掐断
// （浏览器看到 500、服务端日志 socket hang up），所以这一条单独做成 route handler：
// 文件系统路由优先于 rewrite，这里可以自己控制等待时间。
export const dynamic = 'force-dynamic'
export const maxDuration = 300

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000'

export async function GET(req: NextRequest) {
  const target = API_BASE + '/api/report' + req.nextUrl.search
  let res: Response
  try {
    res = await fetch(target, { cache: 'no-store' })
  } catch (err) {
    return new Response(JSON.stringify({ error: 'report service unreachable: ' + String(err) }), {
      status: 502,
      headers: { 'content-type': 'application/json' },
    })
  }
  const body = await res.arrayBuffer()
  return new Response(body, {
    status: res.status,
    headers: {
      'content-type': res.headers.get('content-type') || 'application/zip',
      'content-disposition':
        res.headers.get('content-disposition') || 'attachment; filename="dpv-report.zip"',
      'cache-control': 'no-store',
    },
  })
}
