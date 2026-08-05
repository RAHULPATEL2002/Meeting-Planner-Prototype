/**
 * Conversions between the browser's local wall-clock time and the API's UTC.
 *
 * `<input type="datetime-local">` produces `2026-08-10T09:00` with **no zone**,
 * meaning "09:00 where the user is". The API only accepts unambiguous instants.
 * Getting this wrong is the single most common calendar bug, so the conversion
 * lives in one place with its own unit tests.
 */

/** Local `datetime-local` value -> ISO-8601 UTC (`2026-08-10T07:00:00.000Z`). */
export function localInputToIsoUtc(localValue: string): string {
  // `new Date('2026-08-10T09:00')` is interpreted as local time by the ES spec,
  // which is exactly what the input means.
  return new Date(localValue).toISOString();
}

/** ISO-8601 instant -> value for a `datetime-local` input, in local time. */
export function isoToLocalInput(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** `datetime-local` value for "now, rounded up to the next half hour". */
export function nextHalfHourLocalInput(offsetMinutes = 0): string {
  const date = new Date();
  date.setSeconds(0, 0);
  date.setMinutes(Math.ceil(date.getMinutes() / 30) * 30 + offsetMinutes);
  return isoToLocalInput(date.toISOString());
}

/** "1h 30m", "45m", "2d 3h" — compact and readable at a glance. */
export function formatDuration(minutes: number): string {
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const days = Math.floor(minutes / (60 * 24));
  const hours = Math.floor((minutes % (60 * 24)) / 60);
  const mins = minutes % 60;

  const parts: string[] = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (mins) parts.push(`${mins}m`);
  return parts.join(' ');
}

/** "10 Aug 2026, 09:00 – 10:00" (times collapse when both are the same day). */
export function formatRange(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);

  const day: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' };
  const time: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };

  const sameDay = start.toDateString() === end.toDateString();
  const startText = `${start.toLocaleDateString(undefined, day)}, ${start.toLocaleTimeString(undefined, time)}`;
  const endText = sameDay
    ? end.toLocaleTimeString(undefined, time)
    : `${end.toLocaleDateString(undefined, day)}, ${end.toLocaleTimeString(undefined, time)}`;

  return `${startText} – ${endText}`;
}

/** "in 3 days", "in 2 hours", "yesterday" — relative to now, localised. */
export function formatRelative(iso: string): string {
  const target = new Date(iso).getTime();
  const diffSeconds = Math.round((target - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ];

  for (const [unit, seconds] of units) {
    if (Math.abs(diffSeconds) >= seconds) {
      return formatter.format(Math.round(diffSeconds / seconds), unit);
    }
  }
  return formatter.format(diffSeconds, 'second');
}

/** The browser's IANA zone, used as the default when registering. */
export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}
