;; Batch export org-mode files to RST for Sphinx
;; Usage: emacs --batch -l docs/export.el

(require 'package)
(add-to-list 'package-archives '("melpa" . "https://melpa.org/packages/") t)
(package-initialize)

(unless (package-installed-p 'ox-rst)
  (package-refresh-contents)
  (package-install 'ox-rst))

(require 'ox-rst)
(require 'ox-publish)

;; Prefer Sphinx-friendly RST (no auto section numbers; titles from #+title)
(setq org-export-with-section-numbers nil)
(setq org-export-with-toc nil)
(setq org-export-with-author nil)
(setq org-export-with-timestamps nil)
;; a_b in prose is a snake_case identifier, not a subscript
(setq org-export-with-sub-superscripts nil)
(setq org-rst-headline-underline ?-)

(setq org-publish-project-alist
      '(("sphinx-rst"
         :base-directory "./docs/orgmode/"
         :base-extension "org"
         :publishing-directory "./docs/source/"
         :publishing-function org-rst-publish-to-rst
         :recursive t
         :headline-levels 4
         :with-toc nil
         :section-numbers nil
         :with-author nil)
        ("sphinx-static"
         :base-directory "./docs/orgmode/img/"
         :base-extension "svg\\|png\\|jpg\\|jpeg\\|gif"
         :publishing-directory "./docs/source/img/"
         :publishing-function org-publish-attachment
         :recursive t)
        ("sphinx-all" :components ("sphinx-rst" "sphinx-static"))))

(org-publish "sphinx-all" t)
