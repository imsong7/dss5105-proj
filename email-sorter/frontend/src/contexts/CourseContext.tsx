import { createContext, useContext } from "react";

/** Opens the page for one course. Absent outside the workspace. */
const CourseContext = createContext<((code: string) => void) | null>(null);

export const CourseProvider = CourseContext.Provider;

export function useOpenCourse() {
  return useContext(CourseContext);
}
