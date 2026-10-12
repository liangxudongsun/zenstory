/** Count Unicode codepoints like the backend; never truncate authored input. */
export const MAX_FILE_TITLE_LENGTH = 255;
export function isFileTitleTooLong(title: string): boolean {
  return Array.from(title).length > MAX_FILE_TITLE_LENGTH;
}
