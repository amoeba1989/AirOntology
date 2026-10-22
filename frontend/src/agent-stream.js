// POST + SSE: decode UTF-8 incrementally, including split Chinese characters and CRLF.
export async function readAgentEvents(response, receive) {
  if (!response.ok) {
    let message;
    try { message = (await response.json()).detail; } catch {}
    throw new Error(typeof message === 'string' ? message : `态势分析请求失败（${response.status}）`);
  }
  if (!response.body?.getReader) throw new Error('浏览器不支持流式读取');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', ended = false;
  function consume(final = false) {
    buffer = buffer.replace(/\r\n/g, '\n');
    let split;
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const packet = buffer.slice(0, split); buffer = buffer.slice(split + 2);
      let type = 'message'; const data = [];
      for (const line of packet.split('\n')) {
        if (line.startsWith('event:')) type = line.slice(6).trim();
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (data.length) { receive(type, JSON.parse(data.join('\n'))); if (type === 'done') ended = true; }
    }
    if (buffer.length > 8 * 1024 * 1024) throw new Error('分析快照超出可显示大小');
    if (final && (!ended || buffer.trim())) throw new Error('回答连接提前结束，已显示的卡片仅代表已收到的快照');
  }
  try {
    for (;;) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
      consume(done);
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
