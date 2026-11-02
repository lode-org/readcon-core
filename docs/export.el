;; Batch export org-mode files to RST for Sphinx
;; Usage: emacs --batch -l docs/export.el

(require 'package)
(add-to-list 'package-archives '("melpa" . "https://melpa.org/packages/") t)
(package-initialize)

(unless (package-installed-p 'ox-rst)
  (package-refresh-contents)
  (package-install 'ox-rst))

(require 'org-element)
;; ox-rst from MELPA calls Org 9.7 helpers. Gate the stand-ins on Org 9.6.
(when (version< (org-version) "9.7")
  (unless (fboundp 'org-element-type-p)
    (defun org-element-type-p (node types)
      "Return non-nil when NODE's type is TYPES (symbol or list)."
      (memq (org-element-type node) (if (listp types) types (list types)))))
  (unless (fboundp 'org-element-parent)
    (defun org-element-parent (node)
      "Return NODE's parse-tree parent."
      (org-element-property :parent node)))
  (unless (fboundp 'org-element-begin)
    (defun org-element-begin (node)
      "Return NODE's beginning buffer position."
      (org-element-property :begin node)))
  (unless (fboundp 'org-element-parent-element)
    (defun org-element-parent-element (node)
      "Return the nearest element parent of NODE."
      (let ((parent (org-element-property :parent node)))
        (while (and parent
                    (not (memq (org-element-type parent) org-element-all-elements)))
          (setq parent (org-element-property :parent parent)))
        parent)))
  (unless (fboundp 'org-element-extract)
    (defun org-element-extract (element)
      "Remove ELEMENT from its parse tree."
      (org-element-extract-element element)))
  (defun readcon-org96-lineage (orig datum &optional types &rest rest)
    "Pass a list of types into Org 9.6 `org-element-lineage'."
    (when (symbolp types)
      (setq types (list types)))
    (apply orig datum types rest))
  (advice-add 'org-element-lineage :around #'readcon-org96-lineage))

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

(defvar readcon-repo-root
  (expand-file-name
   ".."
   (file-name-directory (or load-file-name (buffer-file-name) default-directory)))
  "Repository root, so VERSION is found while publishing from docs/orgmode/.")

(defun readcon-version-from-file ()
  "Return the package version stored in VERSION."
  (let ((path (expand-file-name "VERSION" readcon-repo-root)))
    (unless (file-readable-p path)
      (error "VERSION is missing (%s)" path))
    (string-trim
     (with-temp-buffer
       (insert-file-contents path)
       (buffer-string)))))

(defun readcon-substitute-version (_backend)
  "Replace @READCON_VERSION@ from the VERSION file during export."
  (let ((ver (readcon-version-from-file)))
    (goto-char (point-min))
    (while (search-forward "@READCON_VERSION@" nil t)
      (replace-match ver t t))))

(add-hook 'org-export-before-processing-hook #'readcon-substitute-version)

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
