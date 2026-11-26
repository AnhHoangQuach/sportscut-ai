(function (root) {
  const nonEmpty = (value) => typeof value === "string" && value !== ""
  const parseHashtags = (text) => typeof text === "string" ? text.split(/[\s,]+/).filter(Boolean) : []
  const formatHashtags = (tags) => tags.join(" ")
  const copyText = (meta) => `${meta.title}\n${meta.caption}\n${formatHashtags(meta.hashtags)}`

  function clipSources(highlight) {
    if (!nonEmpty(highlight?.clip_url)) return []
    const sources = [{ label: "Bản gốc", url: highlight.clip_url }]
    if (nonEmpty(highlight.voiceover_url)) sources.push({ label: "Lồng tiếng", url: highlight.voiceover_url })
    return sources
  }

  const api = { parseHashtags, formatHashtags, copyText, clipSources }
  root.SportsCutMeta = api
  if (typeof module === "object" && module.exports) module.exports = api
})(globalThis)
