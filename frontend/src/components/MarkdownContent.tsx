import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/**
 * Event descriptions are markdown — Spoonee treats the event page as
 * the paste that Pastebin deleted. react-markdown never renders raw
 * HTML, so viewer-facing pages can render owner-authored text safely.
 */
export function MarkdownContent({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('leading-relaxed', className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ node, ...props }) => <p className="mb-3 last:mb-0" {...props} />,
          a: ({ node, ...props }) => (
            <a
              className="text-hive-accent underline decoration-hive-accent/40 transition-colors hover:decoration-hive-accent"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
          strong: ({ node, ...props }) => (
            <strong className="font-semibold text-hive-text" {...props} />
          ),
          h1: ({ node, ...props }) => (
            <h1 className="mt-5 mb-2 text-lg font-bold text-hive-text first:mt-0" {...props} />
          ),
          h2: ({ node, ...props }) => (
            <h2 className="mt-5 mb-1.5 text-base font-bold text-hive-text first:mt-0" {...props} />
          ),
          h3: ({ node, ...props }) => (
            <h3 className="mt-4 mb-1 text-sm font-semibold text-hive-text first:mt-0" {...props} />
          ),
          ul: ({ node, ...props }) => <ul className="mb-3 list-disc pl-5 last:mb-0" {...props} />,
          ol: ({ node, ...props }) => (
            <ol className="mb-3 list-decimal pl-5 last:mb-0" {...props} />
          ),
          li: ({ node, ...props }) => <li className="mt-1" {...props} />,
          blockquote: ({ node, ...props }) => (
            <blockquote
              className="mb-3 border-l-2 border-hive-border pl-3 text-hive-muted last:mb-0"
              {...props}
            />
          ),
          code: ({ node, ...props }) => (
            <code className="rounded bg-white/10 px-1 py-0.5 font-mono text-[0.9em]" {...props} />
          ),
          hr: ({ node, ...props }) => <hr className="my-4 border-hive-border" {...props} />,
          table: ({ node, ...props }) => (
            <div className="mb-3 overflow-x-auto last:mb-0">
              <table className="border-collapse text-sm" {...props} />
            </div>
          ),
          th: ({ node, ...props }) => (
            <th
              className="border border-hive-border px-2 py-1 text-left font-semibold text-hive-text"
              {...props}
            />
          ),
          td: ({ node, ...props }) => (
            <td className="border border-hive-border px-2 py-1" {...props} />
          ),
        }}>
        {children}
      </Markdown>
    </div>
  )
}
