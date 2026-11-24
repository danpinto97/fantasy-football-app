import { useState, type ReactNode } from "react";

export type PixelArtKind = "standings" | "luck" | "draft" | "agency" | "trade";

const SPRITE: Record<Exclude<PixelArtKind, "standings">, string> = {
  luck: "/sprites/luck.png",
  draft: "/sprites/tux.png",
  agency: "/sprites/ref.png",
  trade: "/sprites/handshake.png",
};

function Sprite({ src, className }: { src: string; className?: string }) {
  return <img className={className ?? "pixel-sprite"} src={src} alt="" draggable={false} />;
}

function Podium() {
  return (
    <div className="podium">
      <div className="podium-col is-2">
        <Sprite src="/sprites/stance-84.png" />
        <div className="riser">2</div>
      </div>
      <div className="podium-col is-1">
        <Sprite src="/sprites/stance-34.png" />
        <div className="riser">1</div>
      </div>
      <div className="podium-col is-3">
        <Sprite src="/sprites/stand-7.png" />
        <div className="riser">3</div>
      </div>
    </div>
  );
}

export function SectionHead({
  art,
  children,
  level = 2,
}: {
  art: PixelArtKind;
  children: ReactNode;
  level?: 2 | 3;
}) {
  const Tag = level === 3 ? "h3" : "h2";
  return (
    <div className="section-head">
      <Tag>{children}</Tag>
      <div className="section-art" aria-hidden="true">
        {art === "standings" ? <Podium /> : <Sprite src={SPRITE[art]} />}
      </div>
    </div>
  );
}

export function FoldSection({
  art,
  title,
  lede,
  defaultOpen = false,
  children,
}: {
  art?: PixelArtKind;
  title: string;
  lede?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="panel fold" open={open}>
      <summary
        className="fold-summary"
        onClick={(event) => {
          event.preventDefault();
          setOpen((current) => !current);
        }}
      >
        <span className="fold-caret" aria-hidden="true" />
        {art ? <SectionHead art={art}>{title}</SectionHead> : <h2>{title}</h2>}
      </summary>
      {lede ? <p className="lede">{lede}</p> : null}
      {children}
    </details>
  );
}

export function PassLoader({ label }: { label: string }) {
  return (
    <div className="pass-loader" role="status" aria-live="polite">
      <div className="pass-field">
        <Sprite className="pass-thrower" src="/sprites/throw-12.png" />
        <div className="pass-arc">
          <svg viewBox="0 0 160 80" preserveAspectRatio="none" aria-hidden="true" focusable="false">
            <path className="pass-dots" d="M 6 54 Q 80 6 154 42" fill="none" />
          </svg>
          <img className="pass-ball" src="/sprites/football.png" alt="" draggable={false} />
        </div>
        <Sprite className="pass-catcher" src="/sprites/catch-24.png" />
      </div>
      <p className="lede">{label}</p>
    </div>
  );
}
