import { courseStyle } from "../domain/course";
import { useOpenCourse } from "../contexts/CourseContext";

export function CourseToken({ code, hue }: { code: string; hue?: number }) {
  const openCourse = useOpenCourse();

  const className = `inline-flex max-w-full items-center truncate rounded-full px-2 py-[2px] text-[11px] font-bold tracking-[0.04em] ${
    hue === undefined ? "bg-surface-muted text-muted" : "bg-[var(--course-bg)] text-[var(--course-text)]"
  }`;

  if (!openCourse) {
    return (
      <span title={`Course ${code}`} style={courseStyle(hue)} className={className}>
        {code}
      </span>
    );
  }

  return (
    <button
      type="button"
      title={`Open ${code}`}
      aria-label={`Open course ${code}`}
      style={courseStyle(hue)}
      onClick={(event) => {
        // The badge sits inside clickable rows; it should not also open the row.
        event.stopPropagation();
        openCourse(code);
      }}
      className={`${className} cursor-pointer hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none`}
    >
      {code}
    </button>
  );
}
