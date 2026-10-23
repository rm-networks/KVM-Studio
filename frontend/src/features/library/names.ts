// Folder and VM names end up as folder names on disk; same rule as the backend.
// eslint-disable-next-line no-control-regex -- control characters are what we reject
const NAME_RE = /^(?![.\s])[^/\\\u0000-\u001f\u007f]{1,64}(?<!\s)$/;

export function isValidName(name: string): boolean {
  return NAME_RE.test(name);
}
