==============
``mod python``
==============


.. rust:module:: readcon_core::python
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::python
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: pyo3::IntoPyObjectExt
      :used_name: IntoPyObjectExt


   .. rust:use:: pyo3::exceptions::PyIOError
      :used_name: PyIOError


   .. rust:use:: pyo3::exceptions::PyTypeError
      :used_name: PyTypeError


   .. rust:use:: pyo3::exceptions::PyValueError
      :used_name: PyValueError


   .. rust:use:: pyo3::types::IntoPyDict
      :used_name: IntoPyDict


   .. rust:use:: pyo3::types::PyDict
      :used_name: PyDict


   .. rust:use:: pyo3::types::PyIterator
      :used_name: PyIterator


   .. rust:use:: pyo3::types::PyList
      :used_name: PyList


   .. rust:use:: pyo3::types::PyTuple
      :used_name: PyTuple


   .. rust:use:: serde_json::Number
      :used_name: Number


   .. rust:use:: serde_json::Value
      :used_name: Value


   .. rust:use:: std::collections::BTreeMap
      :used_name: BTreeMap


   .. rust:use:: std::collections::VecDeque
      :used_name: VecDeque


   .. rust:use:: std::path::Path
      :used_name: Path


   .. rust:use:: readcon_core::iterators::ConFrameIterator
      :used_name: ConFrameIterator


   .. rust:use:: readcon_core::types::AtomDatum
      :used_name: AtomDatum


   .. rust:use:: readcon_core::types::ConFrame
      :used_name: ConFrame


   .. rust:use:: readcon_core::types::ConFrameBuilder
      :used_name: ConFrameBuilder


   .. rust:use:: readcon_core::writer::ConFrameWriter
      :used_name: ConFrameWriter


   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::python::PyAtomDatum
      :index: 1
      :vis: pub
      :toc: struct PyAtomDatum
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"PyAtomDatum"}]

      Python-visible atom data.

      .. rust:variable:: readcon_core::python::PyAtomDatum::symbol
         :index: 2
         :vis: pub
         :toc: symbol
         :layout: [{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"link","value":"String","target":"String"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::x
         :index: 2
         :vis: pub
         :toc: x
         :layout: [{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::y
         :index: 2
         :vis: pub
         :toc: y
         :layout: [{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::z
         :index: 2
         :vis: pub
         :toc: z
         :layout: [{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::fixed
         :index: 2
         :vis: pub
         :toc: fixed
         :layout: [{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::atom_id
         :index: 2
         :vis: pub
         :toc: atom_id
         :layout: [{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::mass
         :index: 2
         :vis: pub
         :toc: mass
         :layout: [{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::vx
         :index: 2
         :vis: pub
         :toc: vx
         :layout: [{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::vy
         :index: 2
         :vis: pub
         :toc: vy
         :layout: [{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::vz
         :index: 2
         :vis: pub
         :toc: vz
         :layout: [{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::fx
         :index: 2
         :vis: pub
         :toc: fx
         :layout: [{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::fy
         :index: 2
         :vis: pub
         :toc: fy
         :layout: [{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyAtomDatum::fz
         :index: 2
         :vis: pub
         :toc: fz
         :layout: [{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]


      .. rubric:: Implementations


      .. rust:impl:: readcon_core::python::PyAtomDatum
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PyAtomDatum","target":"PyAtomDatum"}]
         :toc: impl PyAtomDatum


      .. rust:impl:: readcon_core::python::PyAtomDatum
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PyAtomDatum","target":"PyAtomDatum"}]
         :toc: impl PyAtomDatum


   .. rust:struct:: readcon_core::python::PyConFrame
      :index: 1
      :vis: pub
      :toc: struct PyConFrame
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"PyConFrame"}]

      Python-visible simulation frame.

      .. rust:variable:: readcon_core::python::PyConFrame::cell
         :index: 2
         :vis: pub
         :toc: cell
         :layout: [{"type":"name","value":"cell"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]


      .. rust:variable:: readcon_core::python::PyConFrame::angles
         :index: 2
         :vis: pub
         :toc: angles
         :layout: [{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]


      .. rust:variable:: readcon_core::python::PyConFrame::prebox_header
         :index: 2
         :vis: pub
         :toc: prebox_header
         :layout: [{"type":"name","value":"prebox_header"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyConFrame::postbox_header
         :index: 2
         :vis: pub
         :toc: postbox_header
         :layout: [{"type":"name","value":"postbox_header"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":">"}]


      .. rust:variable:: readcon_core::python::PyConFrame::spec_version
         :index: 2
         :vis: pub
         :toc: spec_version
         :layout: [{"type":"name","value":"spec_version"},{"type":"punctuation","value":": "},{"type":"link","value":"u32","target":"u32"}]


      .. rubric:: Implementations


      .. rust:impl:: readcon_core::python::PyConFrame
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PyConFrame","target":"PyConFrame"}]
         :toc: impl PyConFrame


      .. rust:impl:: readcon_core::python::PyConFrame
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PyConFrame","target":"PyConFrame"}]
         :toc: impl PyConFrame

