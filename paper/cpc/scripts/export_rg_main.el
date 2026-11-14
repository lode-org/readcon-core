;;; Export paper/cpc/src/rg_main.org to the manuscript TeX.
(require 'ox-latex)

(defun readcon-prepare-latex-export ()
  "Register the manuscript class from the preamble comment in this buffer."
  (setq-local org-latex-default-packages-alist nil)
  (setq-local org-latex-packages-alist nil)
  (setq-local org-latex-hyperref-template "")
  (setq-local org-latex-title-command "")
  (setq-local org-latex-toc-command "")
  (setq-local org-latex-compiler-file-string "")
  (setq-local org-export-with-title nil)
  (setq-local org-export-with-author nil)
  (setq-local org-export-with-date nil)
  (setq-local org-export-with-toc nil)
  (setq-local org-export-with-creator nil)
  (setq-local org-export-time-stamp-file nil)
  (setq-local org-export-with-broken-links t)
  (save-excursion
    (goto-char (point-min))
    (re-search-forward "#\\+BEGIN_COMMENT readcon-preamble\n")
    (let ((start (point)))
      (re-search-forward "\n#\\+END_COMMENT")
      (setq-local readcon-latex-header
                  (buffer-substring-no-properties start (match-beginning 0)))))
  (setq-local org-latex-classes
              (list (list "readcon" readcon-latex-header
                          '("\\section{%s}" . "\\section*{%s}")
                          '("\\subsection{%s}" . "\\subsection*{%s}")
                          '("\\subsubsection{%s}" . "\\subsubsection*{%s}"))))
  (add-to-list 'org-export-filter-final-output-functions
               #'readcon-strip-org-wrappers))

(defun readcon-strip-org-wrappers (output &rest _)
  "Drop the empty title and date Org inserts, and keep \\end{document} on the bibliography line."
  (setq output (replace-regexp-in-string "\\\\title[{][}][\n]" "" output t t))
  (setq output (replace-regexp-in-string "\\\\date[{][}][\n]" "" output t t))
  (replace-regexp-in-string " \n\\\\end{document}" " \\end{document}" output t t))

(add-hook 'org-mode-hook #'readcon-prepare-latex-export)
