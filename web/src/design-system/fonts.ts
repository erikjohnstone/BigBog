/**
 * Self-hosted type. Geist Sans (Vercel, SIL OFL 1.1) for the interface and
 * JetBrains Mono (JetBrains, SIL OFL 1.1, via @fontsource-variable) for
 * identifiers, hashes, and every live value. Both are variable fonts so one
 * file each covers the whole weight range. Geist ships no variable italic,
 * so italics are synthesized; the interface barely uses them.
 *
 * The faces are registered from hashed asset URLs so they resolve under any
 * deployment base; a CSS `url()` here would not be rewritten by the bundler.
 */

import '@fontsource-variable/jetbrains-mono';

import geistUrl from './fonts/Geist-Variable.woff2?url';

const css = `
@font-face {
  font-family: "Geist Variable";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("${geistUrl}") format("woff2-variations");
}
`;

const style = document.createElement('style');
style.setAttribute('data-bactalk-fonts', '');
style.textContent = css;
document.head.prepend(style);
