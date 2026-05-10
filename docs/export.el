;; Batch export org-mode files to RST for Sphinx
;; Usage: emacs --batch -l docs/export.el

;; Setup Package Manager (to fetch ox-rst automatically)
(require 'package)
(add-to-list 'package-archives '("melpa" . "https://melpa.org/packages/") t)
(package-initialize)

;; Ensure ox-rst is present
(unless (package-installed-p 'ox-rst)
  (package-refresh-contents)
  (package-install 'ox-rst))

(require 'ox-rst)
(require 'ox-publish)

;; Define the Publishing Project
(setq org-publish-project-alist
      '(("sphinx-rst"
         :base-directory "./docs/orgmode/"
         :base-extension "org"
         :publishing-directory "./docs/source/"
         :publishing-function org-rst-publish-to-rst
         :recursive t
         :headline-levels 4
         :with-toc nil
         :section-numbers nil)
        ("sphinx-static"
         :base-directory "./docs/orgmode/img/"
         :base-extension "svg\\|png\\|jpg\\|jpeg\\|gif"
         :publishing-directory "./docs/source/img/"
         :publishing-function org-publish-attachment
         :recursive t)
        ("sphinx-all" :components ("sphinx-rst" "sphinx-static"))))

;; Run the publish
(org-publish "sphinx-all" t)
