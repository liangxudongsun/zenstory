import React from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Menu, Shield } from "lucide-react";
import { IconButton } from "../ui/IconButton";
import { Button } from "../ui/Button";
import { UserAvatar } from "../UserMenu";
import { useAuth } from "../../contexts/AuthContext";
import { useTranslation } from "react-i18next";

interface AdminHeaderProps {
  onMenuClick: () => void;
  menuOpen: boolean;
  menuButtonRef: React.RefObject<HTMLButtonElement | null>;
}

export const AdminHeader: React.FC<AdminHeaderProps> = ({ onMenuClick, menuOpen, menuButtonRef }) => {
  const navigate = useNavigate();
  const { t } = useTranslation("admin");
  const { user } = useAuth();

  const handleBackToApp = () => {
    navigate("/dashboard");
  };

  return (
    <header inert={menuOpen ? true : undefined} aria-hidden={menuOpen ? true : undefined} className="flex h-14 shrink-0 items-center justify-between border-b border-[hsl(var(--separator-color))] bg-[hsl(var(--bg-secondary))] px-3 sm:px-4">
      <div className="flex items-center gap-3">
        <IconButton
          ref={menuButtonRef}
          onClick={onMenuClick}
          className="md:hidden"
          tone="strong"
          label={t("header.openMenu", "打开管理菜单")}
          icon={<Menu size={20} />}
          aria-expanded={menuOpen}
          aria-controls="admin-mobile-navigation"
          type="button"
        />

        <div className="flex items-center gap-2">
          <Button
            onClick={handleBackToApp}
            variant="ghost"
            size="touch"
            className="px-2.5"
            aria-label={t("header.backToApp", "返回应用")}
            title={t("header.backToApp", "返回应用")}
          >
            <span className="flex items-center gap-1.5"><ArrowLeft size={16} /><span className="hidden sm:inline">{t("header.back", "返回")}</span></span>
          </Button>

          <div className="hidden h-7 w-px bg-[hsl(var(--separator-color))] sm:block" />

          <div className="flex items-center gap-2">
            <div className="hidden h-8 w-8 items-center justify-center rounded-lg bg-[hsl(var(--accent-primary)/0.12)] sm:flex">
              <Shield size={17} className="text-[var(--admin-accent-text)]" />
            </div>
            <span className="text-sm font-semibold text-[hsl(var(--text-primary))]">
              {t("header.title", "管理后台")}
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {user && (
          <div className="flex items-center gap-2 px-1 py-1.5">
            <span className="hidden text-sm text-[hsl(var(--text-secondary))] md:block">
              {user.username}
            </span>
            <UserAvatar
              username={user.username}
              avatarUrl={user.avatar_url}
              size={32}
            />
          </div>
        )}
      </div>
    </header>
  );
};

export default AdminHeader;
