import { createContext, useContext } from "react";

interface AccountShortcut {
  initials: string;
  open: () => void;
  /** Opens the Outlook flow guide. Only set when mail arrives through Power Automate. */
  openSetup?: () => void;
  /** Switch to the other mail source. Only set when the student may choose. */
  switchSource?: () => void;
}

/** The phone's account button (the top bar is hidden there). Absent outside the workspace. */
const AccountContext = createContext<AccountShortcut | null>(null);

export const AccountProvider = AccountContext.Provider;

export function useAccount() {
  return useContext(AccountContext);
}
