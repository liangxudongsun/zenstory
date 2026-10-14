import React, { createContext, useContext, useState, useCallback } from "react";
import type { MobilePanel } from "../components/BottomTabs";

interface MobileLayoutContextType {
  activePanel: MobilePanel;
  setActivePanel: (panel: MobilePanel) => void;
  switchToEditor: () => void;
  switchToFiles: () => void;
  switchToChat: () => void;
  chatFocusRequest: number;
  focusChatInput: () => void;
  isMobile: boolean;
}

const MobileLayoutContext = createContext<MobileLayoutContextType | null>(null);

interface MobileLayoutProviderProps {
  children: React.ReactNode;
  isMobile: boolean;
}

export const MobileLayoutProvider: React.FC<MobileLayoutProviderProps> = ({
  children,
  isMobile,
}) => {
  const [activePanel, setActivePanel] = useState<MobilePanel>("editor");

  const switchToEditor = useCallback(() => {
    if (isMobile) {
      setActivePanel("editor");
    }
  }, [isMobile]);

  const switchToFiles = useCallback(() => {
    if (isMobile) {
      setActivePanel("files");
    }
  }, [isMobile]);

  const switchToChat = useCallback(() => {
    if (isMobile) {
      setActivePanel("chat");
    }
  }, [isMobile]);

  const [chatFocusRequest, setChatFocusRequest] = useState(0);
  const focusChatInput = useCallback(() => {
    setActivePanel("chat");
    setChatFocusRequest(value => value + 1);
  }, []);

  return (
    <MobileLayoutContext.Provider
      value={{
        activePanel,
        setActivePanel,
        switchToEditor,
        switchToFiles,
        switchToChat,
        chatFocusRequest,
        focusChatInput,
        isMobile,
      }}
    >
      {children}
    </MobileLayoutContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useMobileLayout = (): MobileLayoutContextType => {
  const context = useContext(MobileLayoutContext);
  if (!context) {
    // Return a default context for desktop mode
    return {
      activePanel: "editor",
      setActivePanel: () => {},
      switchToEditor: () => {},
      switchToFiles: () => {},
      switchToChat: () => {},
      chatFocusRequest: 0,
      focusChatInput: () => {},
      isMobile: false,
    };
  }
  return context;
};
