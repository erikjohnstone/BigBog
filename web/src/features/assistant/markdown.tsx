import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { useMemo } from 'react';

import { cn } from '../../design-system/cn';

marked.setOptions({ gfm: true, breaks: true });

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

/** Model output rendered as sanitized HTML. Nothing from the model runs as code. */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(source, { async: false }) as string, { USE_PROFILES: { html: true } }), [source]);
  return <div className={cn('md', className)} dangerouslySetInnerHTML={{ __html: html }} />;
}
