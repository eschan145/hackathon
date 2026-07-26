import { useEffect, useRef, useState } from "react";
import { HelpIcon, SearchIcon } from "../lib/icons";

interface Props {
  title: string;
  subtitle: string;
  /** When provided, the search button reveals a filter field wired to this. */
  search?: { value: string; onChange: (v: string) => void; placeholder?: string };
  help?: string[];
}

export default function PageHeader({ title, subtitle, search, help }: Props) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) inputRef.current?.focus();
  }, [searchOpen]);

  function toggleSearch() {
    if (searchOpen && search) search.onChange("");
    setSearchOpen((o) => !o);
    setHelpOpen(false);
  }

  return (
    <header className="page-header">
      <div className="page-heading">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>

      <div className="header-actions">
        {searchOpen && search && (
          <input
            ref={inputRef}
            className="header-search"
            value={search.value}
            placeholder={search.placeholder ?? "Search"}
            onChange={(e) => search.onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") toggleSearch();
            }}
          />
        )}
        <button
          className={`icon-btn${searchOpen ? " on" : ""}`}
          onClick={toggleSearch}
          disabled={!search}
          title={search ? "Search" : "Search unavailable on this view"}
          aria-label="Search"
        >
          <SearchIcon />
        </button>
        <div className="help-wrap">
          <button
            className={`icon-btn${helpOpen ? " on" : ""}`}
            onClick={() => setHelpOpen((o) => !o)}
            disabled={!help?.length}
            title="About this view"
            aria-label="Help"
          >
            <HelpIcon />
          </button>
          {helpOpen && help?.length ? (
            <div className="help-popover">
              <span className="help-title">About this view</span>
              <ul>
                {help.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
