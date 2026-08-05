import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AvatarComponent } from './avatar.component';

describe('AvatarComponent', () => {
  let fixture: ComponentFixture<AvatarComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [AvatarComponent] }).compileComponents();
    fixture = TestBed.createComponent(AvatarComponent);
  });

  function render(name: string, url: string | null = null): HTMLElement {
    fixture.componentRef.setInput('name', name);
    fixture.componentRef.setInput('url', url);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('renders an image when an avatar URL is present', () => {
    const image = render('Alice Adams', '/static/avatars/abc.jpg').querySelector('img');
    expect(image?.getAttribute('src')).toBe('/static/avatars/abc.jpg');
    expect(image?.getAttribute('alt')).toBe('Alice Adams');
  });

  it('falls back to initials from the first and last name', () => {
    expect(render('Alice Adams').textContent?.trim()).toBe('AA');
    expect(render('Bob Van Der Berg').textContent?.trim()).toBe('BB');
  });

  it('uses the first two letters for a single-word name', () => {
    expect(render('Mallory').textContent?.trim()).toBe('MA');
  });

  it('does not crash on an empty name', () => {
    expect(render('   ').textContent?.trim()).toBe('?');
  });

  it('gives the same person the same colour every time', () => {
    const first = render('Alice Adams').querySelector('span')?.style.background;
    const second = render('Alice Adams').querySelector('span')?.style.background;
    const other = render('Bob Brown').querySelector('span')?.style.background;

    expect(first).toBe(second!);
    expect(first).not.toBe(other!);
  });

  it('exposes the name to screen readers when showing initials', () => {
    const span = render('Alice Adams').querySelector('span');
    expect(span?.getAttribute('aria-label')).toBe('Alice Adams');
  });
});
