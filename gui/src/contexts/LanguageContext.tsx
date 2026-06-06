"use client";

import React, { createContext, useContext, useState, ReactNode } from "react";

type Language = "pt" | "en";

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

const translations = {
  pt: {
    dashboard_title: "Painel de Controle",
    bot_status: "Status do Bot",
    running: "Executando",
    idle: "Inativo",
    start_bot: "Iniciar Bot",
    stop_bot: "Parar Bot",
    total_evaluated: "Perfis Avaliados",
    total_followed: "Follows Realizados",
    total_starred: "Stars Distribuídas",
    purge_queue_size: "Fila de Purga",
    nav_home: "Dashboard",
    nav_console: "Terminal Console",
    nav_strategy: "Estratégia",
    nav_purge: "Purga & Whitelist",
    version: "Versão",
    status: "STATUS",
    quick_tips: "Dicas e Recomendações",
    env_editor: "Editor de Configurações (.env)",
    lang_label: "Linguagem Alvo (LANGUAGE)",
    fetch_label: "Quota de Busca por Ciclo (FETCH_COUNT)",
    sub_threshold_label: "Nota para Seguir (SUBSCRIBE_THRESHOLD)",
    star_threshold_label: "Nota para Dar Star (STAR_THRESHOLD)",
    save_settings: "Salvar Configurações",
    add_user: "Adicionar Usuário",
    whitelist_placeholder: "Nome de usuário do GitHub (ex: torvalds)",
    unfollow_log_title: "Logs de Perfis Removidos",
    unfollow_log_desc: "Esses perfis foram removidos e não serão seguidos novamente.",
    protected_accounts: "Contas Protegidas (Whitelist)",
    clear_screen: "Limpar Tela",
    tip_star_threshold: "Dica de Star: Um limite de 16.0 garante que você dê star apenas em projetos excepcionais, atraindo desenvolvedores de alto nível para o seu perfil.",
    tip_fetch_limit: "Dica de Limite: Limitar o número de repositórios por ciclo a 5 ou 10 previne chamadas excessivas e mitiga riscos de banimento pelo GitHub.",
    tip_subscribe_threshold: "Dica de Follow: Um limite de 14.0 atinge autores com projetos bem estruturados que têm alta probabilidade de seguir de volta.",
    console_idle: "Nenhum log ativo. Ative o bot no painel para ver logs de processamento.",
    change_language: "Mudar Idioma",
    active: "ATIVO",
    inactive: "INATIVO",
    saved_success: "Configurações salvas!",
    error_saving: "Erro ao salvar:",
    bot_started_msg: "[SISTEMA] Iniciando processo Python...",
    bot_stopped_msg: "[SISTEMA] Bot parado pelo usuário."
  },
  en: {
    dashboard_title: "Control Desk",
    bot_status: "Bot Status",
    running: "Running",
    idle: "Idle",
    start_bot: "Start Bot",
    stop_bot: "Stop Bot",
    total_evaluated: "Profiles Rated",
    total_followed: "Follows Made",
    total_starred: "Stars Made",
    purge_queue_size: "Purge Queue",
    nav_home: "Dashboard",
    nav_console: "Console",
    nav_strategy: "Strategy",
    nav_purge: "Purge & Whitelist",
    version: "Version",
    status: "STATUS",
    quick_tips: "Tips & Recommendations",
    env_editor: "Configuration Editor (.env)",
    lang_label: "Target Language (LANGUAGE)",
    fetch_label: "Fetch Quota Per Cycle (FETCH_COUNT)",
    sub_threshold_label: "Subscribe Threshold",
    star_threshold_label: "Star Threshold",
    save_settings: "Save Settings",
    add_user: "Add User",
    whitelist_placeholder: "GitHub username (e.g. torvalds)",
    unfollow_log_title: "Unfollowed Profiles Log",
    unfollow_log_desc: "These profiles have been unfollowed and will not be followed again.",
    protected_accounts: "Protected Accounts (Whitelist)",
    clear_screen: "Clear Screen",
    tip_star_threshold: "Star Tip: A threshold of 16.0 ensures you only star outstanding projects, attracting senior-level devs to your profile.",
    tip_fetch_limit: "Fetch Tip: Keeping the fetch quota per cycle low (e.g. 5-10) prevents rate-limit abuse and mitigates ban risks.",
    tip_subscribe_threshold: "Follow Tip: A threshold of 14.0 targets authors with high-quality repositories who are likely to follow you back.",
    console_idle: "No active logs. Turn on the bot to stream processing logs.",
    change_language: "Change Language",
    active: "ACTIVE",
    inactive: "INACTIVE",
    saved_success: "Settings saved!",
    error_saving: "Error saving:",
    bot_started_msg: "[SYSTEM] Spawning Python process...",
    bot_stopped_msg: "[SYSTEM] Bot stopped by user."
  }
};

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>("pt");

  const t = (key: string): string => {
    const dict = translations[language];
    return (dict as any)[key] || key;
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
}
