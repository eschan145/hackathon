interface LogoProps {
  size?: number;
  wordmark?: boolean;
  monochrome?: boolean;
  className?: string;
}

export default function OrchestratrLogo({
  size = 32,
  wordmark = false,
  monochrome = false,
  className = "",
}: LogoProps) {
  return (
    <span className={`orchestratr-logo${wordmark ? " with-wordmark" : ""} ${className}`.trim()}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 40 40"
        fill="none"
        role="img"
        aria-label={wordmark ? undefined : "Orchestratr"}
      >
        <path d="M18.2 4.4 9.1 7.7 4.4 16.4l5.8 3.1 3.4-5.9 5.9-2.2-1.3-7Z" fill="currentColor" />
        <path d="m35.6 18.2-3.3-9.1-8.7-4.7-3.1 5.8 5.9 3.4 2.2 5.9 7-1.3Z" fill="currentColor" />
        <path d="m21.8 35.6 9.1-3.3 4.7-8.7-5.8-3.1-3.4 5.9-5.9 2.2 1.3 7Z" fill="currentColor" />
        <path d="m4.4 21.8 3.3 9.1 8.7 4.7 3.1-5.8-5.9-3.4-2.2-5.9-7 1.3Z" fill="currentColor" />
        <path
          d="m20.5 10.2 5.9 3.4 2.2 5.9-5.9 2.1-4.3-4.3 2.1-7.1Z"
          fill={monochrome ? "currentColor" : "#5658C9"}
        />
        <path d="m10.2 19.5 3.4-5.9 5.9-2.2-1.1 5.9-4.8 4.3-3.4-2.1Z" fill="#FFFDF8" />
      </svg>
      {wordmark && <span className="orchestratr-wordmark">Orchestratr</span>}
    </span>
  );
}
