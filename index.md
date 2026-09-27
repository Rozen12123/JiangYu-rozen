---
title: ""
excerpt: ""
author_profile: true
---

<span class='anchor' id='about-me'></span>

# 👨‍🎓 About Me

I am interested in **reliable reasoning for foundation models**, with a particular focus on reasoning verification, neuro-symbolic reasoning, and trustworthy AI. My research studies how to identify, verify, and improve failures in multi-step reasoning systems.

I am especially interested in combining formal or probabilistic reasoning with modern language models, and in developing interpretable signals for understanding when and why reasoning fails.

My research interests include **Reasoning Verification**, **Neuro-Symbolic AI**, **Trustworthy Foundation Models**, and **Formal & Probabilistic Reasoning**.

# ✨ News

- *2026.09*: &nbsp;🎉 **Mining Logic under Uncertainty** was accepted by **NeurIPS 2026**.
- *2026*: &nbsp;🏆 **Logical-SAGE** received an **Outstanding Paper Award** at the **AAAI 2026 Bridge on Logical and Symbolic Reasoning in Language Models**.
- *2026*: &nbsp;🎉 **LogicSAGE** was accepted by **ICML 2026**.

# 📝 Publications

*<sup>*</sup> Equal contribution.*

{% for paper in site.data.publications %}
<p>
<a href="{{ paper.url }}"><strong>{{ paper.title }}</strong></a><br>
{{ paper.authors_html }}<br>
<strong>{{ paper.venue }}</strong>{% if paper.award and paper.award != "" %} · <strong>{{ paper.award }}</strong>{% endif %}
</p>
{% endfor %}

# 🔬 Research

- **Reasoning Verification.** Auditing multi-step reasoning and checking whether conclusions are supported by valid reasoning processes.
- **Neuro-Symbolic Reasoning.** Combining foundation models with structured, formal, and probabilistic reasoning mechanisms.
- **Reasoning Dynamics.** Studying internal representations and signals associated with reasoning failures and change points.
- **Trustworthy AI.** Building verification and diagnostic tools that make foundation-model behavior more reliable and interpretable.
