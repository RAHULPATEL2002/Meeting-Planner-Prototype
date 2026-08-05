import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Circular avatar with a deterministic initials fallback.
 *
 * Most participants will not have uploaded a picture (some are not even
 * registered), so the fallback is the common case, not the error case. The
 * colour is derived from the name, which keeps a person's tile stable across
 * pages without storing anything.
 */
@Component({
  selector: 'app-avatar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (url()) {
      <img class="avatar" [src]="url()" [alt]="name()" [style.width.px]="size()" [style.height.px]="size()" />
    } @else {
      <span
        class="avatar avatar--initials"
        [style.width.px]="size()"
        [style.height.px]="size()"
        [style.font-size.px]="size() * 0.4"
        [style.background]="colour()"
        [attr.aria-label]="name()"
        >{{ initials() }}</span
      >
    }
  `,
  styles: [
    `
      .avatar {
        border-radius: 50%;
        object-fit: cover;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        background: var(--surface-2);
      }
      .avatar--initials {
        color: #fff;
        font-weight: 600;
        letter-spacing: 0.02em;
        user-select: none;
      }
    `,
  ],
})
export class AvatarComponent {
  readonly name = input.required<string>();
  readonly url = input<string | null>(null);
  readonly size = input(40);

  protected readonly initials = computed(() => {
    const parts = this.name().trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) {
      return '?';
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  });

  /** Stable hue per name — same person, same colour, no lookup table. */
  protected readonly colour = computed(() => {
    const name = this.name();
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = (hash * 31 + name.charCodeAt(i)) | 0;
    }
    return `hsl(${Math.abs(hash) % 360} 55% 45%)`;
  });
}
