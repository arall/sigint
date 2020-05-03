export function escapeUnicode(str) {
  return str.replace(
    /[^\0-~]/g,
    c => '\\u' + ('000' + c.charCodeAt().toString(16)).slice(-4)
  )
}
