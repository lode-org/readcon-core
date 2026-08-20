;;; org2tex.el --- Export paper/cpc/src/rg_main.org to LaTeX
;;; Commentary:
;; Same exporter contract as the amsel CPC paper (elsarticle preprint).
;; Usage from repo root:
;;   emacs -nl --script paper/cpc/scripts/org2tex.el paper/cpc/src/rg_main.org

;;; Code:

(setq hz-packages '(org-ref org use-package org-contrib))

(require 'package)
(setq package-user-dir
      (or (and (getenv "CONDA_PREFIX")
               (concat (getenv "CONDA_PREFIX") "/emacs_packages"))
          (expand-file-name "~/.emacs.d/elpa")))
(add-to-list 'package-archives '("melpa" . "https://melpa.org/packages/") t)
(add-to-list 'package-archives '("nongnu" . "https://elpa.nongnu.org/nongnu/") t)
(package-initialize)

(let ((refreshed nil))
  (when (not package-archive-contents)
    (package-refresh-contents)
    (setq refreshed t))
  (dolist (pkg hz-packages)
    (when (and (not (package-installed-p pkg))
               (assoc pkg package-archive-contents))
      (unless refreshed
        (package-refresh-contents)
        (setq refreshed t))
      (package-install pkg))))

(require 'org)
(org-babel-do-load-languages 'org-babel-load-languages '((dot . t)))
(setq org-confirm-babel-evaluate nil)

(when (require 'ox-extra nil t)
  (ox-extras-activate '(ignore-headlines)))

(add-to-list 'org-latex-classes
             '("elsarticle" "\\documentclass[preprint,12pt]{elsarticle}"
               ("\\section{%s}" . "\\section*{%s}")
               ("\\subsection{%s}" . "\\subsection*{%s}")
               ("\\subsubsection{%s}" . "\\subsubsection*{%s}")
               ("\\paragraph{%s}" . "\\paragraph*{%s}")
               ("\\subparagraph{%s}" . "\\subparagraph*{%s}")))
(setq org-latex-packages-alist nil)
(setq org-latex-prefer-user-labels t)
(setq org-latex-listings t)
(setq org-latex-src-block-backend 'listings)
(setq org-latex-default-packages-alist
      '(("" "graphicx" t)
        ("" "rotating" nil)
        ("normalem" "ulem" t)))

(defun hz-ignore-headline (contents backend info)
  "Drop headlines tagged ignoreheading (amsel CPC exporter)."
  (when (and (org-export-derived-backend-p backend 'latex 'html 'ascii)
             (string-match "\\(\\`.*\\)ignoreheading\\(.*\n\\)"
                           (downcase contents)))
    (replace-match "" nil nil contents)))

(defun hz-export-org-files (files)
  "Export each org file in FILES to LaTeX."
  (add-to-list 'org-export-filter-headline-functions 'hz-ignore-headline)
  (setq org-export-with-broken-links t)
  (dolist (org-file files)
    (message "*** Exporting file %s ***" org-file)
    (find-file org-file)
    (org-latex-export-to-latex)
    (kill-buffer)))

(hz-export-org-files argv)

;; Local Variables:
;; mode: emacs-lisp
;; End:
