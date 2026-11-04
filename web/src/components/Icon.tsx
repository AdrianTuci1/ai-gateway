import type { SVGProps } from "react";

const paths: Record<string, string> = {
  home: "M2 8 8 3l6 5v7H2V8Z",
  grid: "M2 2h5v5H2V2Zm7 0h5v5H9V2ZM2 9h5v5H2V9Zm7 0h5v5H9V9Z",
  cube: "M8 1.5 14 5v6L8 14.5 2 11V5l6-3.5Z M2 5l6 3.5L14 5 M8 8.5v6",
  layers: "M8 1.5 14.5 5 8 8.5 1.5 5 8 1.5Z M1.5 8 8 11.5 14.5 8 M1.5 11 8 14.5 14.5 11",
  users:
    "M5.5 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm5 0a2 2 0 1 0 0-4 M1 14c0-2.2 2-4 4.5-4S10 11.8 10 14 M10.5 10c2 .3 3.5 1.9 3.5 4",
  activity: "M1 8h3l2-5 3 10 2-5h4",
  shield: "M8 1.5 13.5 3.5v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4L8 1.5Z",
  search: "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm4-1 3.5 3.5",
  refresh: "M13.5 8a5.5 5.5 0 1 1-1.6-3.9 M13.5 2v3h-3",
  plus: "M8 2v12 M2 8h12",
  chevron: "M5 3l5 5-5 5",
  arrowLeft: "M13 8H3 M7 4 3 8l4 4",
  chevronDown: "M3 5l5 5 5-5",
  close: "M3 3l10 10 M13 3L3 13",
  more: "M3 8h.01 M8 8h.01 M13 8h.01",
  menu: "M2 4h12 M2 8h12 M2 12h12",
  panel: "M2 3h12v10H2V3Z M6 3v10",
  settings: "M8 10.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4Z M8 1.5l1 1.7 2-.4.5 2 1.8 1-1 1.8 1 1.8-1.8 1-.5 2-2-.4-1 1.7-1-1.7-2 .4-.5-2-1.8-1 1-1.8-1-1.8 1.8-1 .5-2 2 .4 1-1.7Z",
  audit: "M3 1.5h7l3 3v10H3v-13Z M6 6h4 M6 9h4 M6 12h2",
  trace: "M2 3h4v3H2V3Zm8 7h4v3h-4v-3ZM6 4.5h2a2 2 0 0 1 2 2v3",
  key: "M10 2a4 4 0 1 1-3.6 5.8L2 12.2V14h2v-2h2v-2h1.2A4 4 0 0 1 10 2Z",
  server: "M2 2h12v4H2V2Zm0 8h12v4H2v-4Z M4 4h.01 M4 12h.01",
  agent: "M8 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z M3 14v-2a3 3 0 0 1 3-3h4a3 3 0 0 1 3 3v2",
  wand: "M2 14 11 5 M9 3l1 1 M12 6l1 1 M13 2l1 3-3-1",
  external: "M6 3H3v10h10v-3 M9 2h5v5 M14 2 7 9",
  download: "M8 2v8 M4 7l4 4 4-4 M2 13h12",
  alert: "M8 2 15 14H1L8 2Z M8 6v4 M8 12h.01",
  check: "M2 8l4 4 8-8",
  dot: "M8 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  sort: "M5 3v10 M2 10l3 3 3-3 M11 13V3 M8 6l3-3 3 3",
  filter: "M2 3h12l-4.5 5.5V13l-3 1.5V8.5L2 3Z",
  link: "M6.5 9.5 9.5 6.5 M5 11l-1 1a2.8 2.8 0 0 1-4-4l2-2a2.8 2.8 0 0 1 4 0 M11 5l1-1a2.8 2.8 0 0 1 4 4l-2 2a2.8 2.8 0 0 1-4 0",
};

export type IconName = keyof typeof paths;

type Props = SVGProps<SVGSVGElement> & {
  name: IconName | string;
  size?: number;
};

export function Icon({ name, size = 16, ...rest }: Props) {
  const d = paths[name] ?? paths.dot;
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
