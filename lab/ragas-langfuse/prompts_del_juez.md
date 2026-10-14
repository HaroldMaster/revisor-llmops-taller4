# Los prompts del juez de RAGAS — `ragas` 0.4.3

Generado por `python evaluar_ragas.py prompts` a partir de la librería instalada: es **exactamente** el texto que recibe el juez, con la instrucción, el esquema JSON de salida, los ejemplos *few-shot* de la librería y el caso de `resultados/verificar.json` como entrada. Las afirmaciones del paso 2 son las que el juez extrajo en el paso 1 de esa corrida. Licencia de `ragas`: Apache-2.0.


## Fidelidad, paso 1 — extraer afirmaciones de la respuesta

Clase: `StatementGeneratorPrompt` · salida: `StatementGeneratorOutput`

```text
Given a question and an answer, analyze the complexity of each sentence in the answer. Break down each sentence into one or more fully understandable statements. Ensure that no pronouns are used in any statement.
Please return the output in a JSON format that complies with the following schema as specified in JSON Schema:
{"description": "Structured output for statement generation.", "properties": {"statements": {"description": "The generated statements from the answer", "items": {"type": "string"}, "title": "Statements", "type": "array"}}, "required": ["statements"], "title": "StatementGeneratorOutput", "type": "object"}Do not use single quotes in your response but double quotes,properly escaped with a backslash.

--------EXAMPLES-----------
Example 1
Input: {
    "question": "Who was Albert Einstein and what is he best known for?",
    "answer": "He was a German-born theoretical physicist, widely acknowledged to be one of the greatest and most influential physicists of all time. He was best known for developing the theory of relativity, he also made important contributions to the development of the theory of quantum mechanics."
}
Output: {
    "statements": [
        "Albert Einstein was a German-born theoretical physicist.",
        "Albert Einstein is recognized as one of the greatest and most influential physicists of all time.",
        "Albert Einstein was best known for developing the theory of relativity.",
        "Albert Einstein made important contributions to the development of the theory of quantum mechanics."
    ]
}
-----------------------------

Now perform the same with the following input
input: {
    "question": "¿Cuántos días de vacaciones puedo transferir al año siguiente?",
    "answer": "Puedes transferir hasta 5 días; la solicitud se hace al jefe antes de diciembre."
}
Output: 
```

## Fidelidad, paso 2 — verificar cada afirmación contra el contexto

Clase: `NLIStatementPrompt` · salida: `NLIStatementOutput`

```text
Your task is to judge the faithfulness of a series of statements based on a given context. For each statement you must return verdict as 1 if the statement can be directly inferred based on the context or 0 if the statement can not be directly inferred based on the context.
Please return the output in a JSON format that complies with the following schema as specified in JSON Schema:
{"$defs": {"StatementFaithfulnessAnswer": {"description": "Individual statement with reason and verdict for NLI evaluation.", "properties": {"statement": {"description": "the original statement, word-by-word", "title": "Statement", "type": "string"}, "reason": {"description": "the reason of the verdict", "title": "Reason", "type": "string"}, "verdict": {"description": "the verdict(0/1) of the faithfulness", "title": "Verdict", "type": "integer"}}, "required": ["statement", "reason", "verdict"], "title": "StatementFaithfulnessAnswer", "type": "object"}}, "description": "Structured output for NLI statement evaluation.", "properties": {"statements": {"description": "Evaluated statements with verdicts", "items": {"$ref": "#/$defs/StatementFaithfulnessAnswer"}, "title": "Statements", "type": "array"}}, "required": ["statements"], "title": "NLIStatementOutput", "type": "object"}Do not use single quotes in your response but double quotes,properly escaped with a backslash.

--------EXAMPLES-----------
Example 1
Input: {
    "context": "John is a student at XYZ University. He is pursuing a degree in Computer Science. He is enrolled in several courses this semester, including Data Structures, Algorithms, and Database Management. John is a diligent student and spends a significant amount of time studying and completing assignments. He often stays late in the library to work on his projects.",
    "statements": [
        "John is majoring in Biology.",
        "John is taking a course on Artificial Intelligence.",
        "John is a dedicated student.",
        "John has a part-time job."
    ]
}
Output: {
    "statements": [
        {
            "statement": "John is majoring in Biology.",
            "reason": "John's major is explicitly stated as Computer Science, not Biology.",
            "verdict": 0
        },
        {
            "statement": "John is taking a course on Artificial Intelligence.",
            "reason": "The context mentions courses in Data Structures, Algorithms, and Database Management, but does not mention Artificial Intelligence.",
            "verdict": 0
        },
        {
            "statement": "John is a dedicated student.",
            "reason": "The context states that John is a diligent student who spends a significant amount of time studying and completing assignments.",
            "verdict": 1
        },
        {
            "statement": "John has a part-time job.",
            "reason": "There is no information in the context about John having a part-time job.",
            "verdict": 0
        }
    ]
}
-----------------------------

Now perform the same with the following input
input: {
    "context": "Política de vacaciones de NimbusSoft: Los días no utilizados pueden transferirse al año siguiente hasta un máximo de 5 días.\nPolítica de reembolso de gastos de NimbusSoft: El límite diario de alimentación en viajes es de 45 USD.",
    "statements": [
        "One can transfer up to 5 vacation days to the following year.",
        "The request to transfer vacation days is made to the supervisor before December."
    ]
}
Output: 
```

## Relevancia de la respuesta — una pregunta desde la respuesta (se repite n = 3 veces)

Clase: `AnswerRelevancePrompt` · salida: `AnswerRelevanceOutput`

```text
Generate a question for the given answer and identify if the answer is noncommittal.
Give noncommittal as 1 if the answer is noncommittal (evasive, vague, or ambiguous) and 0 if the answer is substantive.
Examples of noncommittal answers: "I don't know", "I'm not sure", "It depends".
Please return the output in a JSON format that complies with the following schema as specified in JSON Schema:
{"description": "Structured output for answer relevance question generation.", "properties": {"question": {"description": "Question that can be answered from the response", "title": "Question", "type": "string"}, "noncommittal": {"description": "1 if the response is evasive/vague, 0 if it is substantive", "title": "Noncommittal", "type": "integer"}}, "required": ["question", "noncommittal"], "title": "AnswerRelevanceOutput", "type": "object"}Do not use single quotes in your response but double quotes,properly escaped with a backslash.

--------EXAMPLES-----------
Example 1
Input: {
    "response": "Albert Einstein was born in Germany."
}
Output: {
    "question": "Where was Albert Einstein born?",
    "noncommittal": 0
}

Example 2
Input: {
    "response": "The capital of France is Paris, a city known for its architecture and culture."
}
Output: {
    "question": "What is the capital of France?",
    "noncommittal": 0
}

Example 3
Input: {
    "response": "I don't know about the groundbreaking feature of the smartphone invented in 2023 as I am unaware of information beyond 2022."
}
Output: {
    "question": "What was the groundbreaking feature of the smartphone invented in 2023?",
    "noncommittal": 1
}
-----------------------------

Now perform the same with the following input
input: {
    "response": "Puedes transferir hasta 5 días; la solicitud se hace al jefe antes de diciembre."
}
Output: 
```

## Precisión del contexto — un juicio por fragmento (aquí, el primero)

Clase: `ContextPrecisionPrompt` · salida: `ContextPrecisionOutput`

```text
Given question, answer and context verify if the context was useful in arriving at the given answer. Give verdict as "1" if useful and "0" if not with json output.
Please return the output in a JSON format that complies with the following schema as specified in JSON Schema:
{"description": "Structured output for context precision evaluation.", "properties": {"reason": {"description": "Reason for verification", "title": "Reason", "type": "string"}, "verdict": {"description": "Binary (0/1) verdict of verification", "title": "Verdict", "type": "integer"}}, "required": ["reason", "verdict"], "title": "ContextPrecisionOutput", "type": "object"}Do not use single quotes in your response but double quotes,properly escaped with a backslash.

--------EXAMPLES-----------
Example 1
Input: {
    "question": "What can you tell me about Albert Einstein?",
    "context": "Albert Einstein (14 March 1879 – 18 April 1955) was a German-born theoretical physicist, widely held to be one of the greatest and most influential scientists of all time. Best known for developing the theory of relativity, he also made important contributions to quantum mechanics, and was thus a central figure in the revolutionary reshaping of the scientific understanding of nature that modern physics accomplished in the first decades of the twentieth century. His mass–energy equivalence formula E = mc2, which arises from relativity theory, has been called 'the world's most famous equation'. He received the 1921 Nobel Prize in Physics 'for his services to theoretical physics, and especially for his discovery of the law of the photoelectric effect', a pivotal step in the development of quantum theory. His work is also known for its influence on the philosophy of science. In a 1999 poll of 130 leading physicists worldwide by the British journal Physics World, Einstein was ranked the greatest physicist of all time. His intellectual achievements and originality have made Einstein synonymous with genius.",
    "answer": "Albert Einstein, born on 14 March 1879, was a German-born theoretical physicist, widely held to be one of the greatest and most influential scientists of all time. He received the 1921 Nobel Prize in Physics for his services to theoretical physics."
}
Output: {
    "reason": "The provided context was indeed useful in arriving at the given answer. The context includes key information about Albert Einstein's life and contributions, which are reflected in the answer.",
    "verdict": 1
}

Example 2
Input: {
    "question": "who won 2020 icc world cup?",
    "context": "The 2022 ICC Men's T20 World Cup, held from October 16 to November 13, 2022, in Australia, was the eighth edition of the tournament. Originally scheduled for 2020, it was postponed due to the COVID-19 pandemic. England emerged victorious, defeating Pakistan by five wickets in the final to clinch their second ICC Men's T20 World Cup title.",
    "answer": "England"
}
Output: {
    "reason": "the context was useful in clarifying the situation regarding the 2020 ICC World Cup and indicating that England was the winner of the tournament that was intended to be held in 2020 but actually took place in 2022.",
    "verdict": 1
}

Example 3
Input: {
    "question": "What is the tallest mountain in the world?",
    "context": "The Andes is the longest continental mountain range in the world, located in South America. It stretches across seven countries and features many of the highest peaks in the Western Hemisphere. The range is known for its diverse ecosystems, including the high-altitude Andean Plateau and the Amazon rainforest.",
    "answer": "Mount Everest."
}
Output: {
    "reason": "the provided context discusses the Andes mountain range, which, while impressive, does not include Mount Everest or directly relate to the question about the world's tallest mountain.",
    "verdict": 0
}
-----------------------------

Now perform the same with the following input
input: {
    "question": "¿Cuántos días de vacaciones puedo transferir al año siguiente?",
    "context": "Política de vacaciones de NimbusSoft: Los días no utilizados pueden transferirse al año siguiente hasta un máximo de 5 días.",
    "answer": "Hasta un máximo de 5 días."
}
Output: 
```

## Recall del contexto — las afirmaciones de la referencia contra el contexto

Clase: `ContextRecallPrompt` · salida: `ContextRecallOutput`

```text
Given a context and an answer, analyze each statement in the answer and classify if the statement can be attributed to the given context or not.
Use only binary classification: 1 if the statement can be attributed to the context, 0 if it cannot.
Provide detailed reasoning for each classification.
Please return the output in a JSON format that complies with the following schema as specified in JSON Schema:
{"$defs": {"ContextRecallClassification": {"description": "Classification of a single statement.", "properties": {"statement": {"description": "Individual statement extracted from the answer", "title": "Statement", "type": "string"}, "reason": {"description": "Reasoning for why the statement is or isn't attributable to context", "title": "Reason", "type": "string"}, "attributed": {"description": "Binary classification: 1 if the statement can be attributed to context, 0 otherwise", "title": "Attributed", "type": "integer"}}, "required": ["statement", "reason", "attributed"], "title": "ContextRecallClassification", "type": "object"}}, "description": "Structured output for context recall classifications.", "properties": {"classifications": {"description": "List of statement classifications", "items": {"$ref": "#/$defs/ContextRecallClassification"}, "title": "Classifications", "type": "array"}}, "required": ["classifications"], "title": "ContextRecallOutput", "type": "object"}Do not use single quotes in your response but double quotes,properly escaped with a backslash.

--------EXAMPLES-----------
Example 1
Input: {
    "question": "What can you tell me about Albert Einstein?",
    "context": "Albert Einstein (14 March 1879 - 18 April 1955) was a German-born theoretical physicist, widely held to be one of the greatest and most influential scientists of all time. Best known for developing the theory of relativity, he also made important contributions to quantum mechanics, and was thus a central figure in the revolutionary reshaping of the scientific understanding of nature that modern physics accomplished in the first decades of the twentieth century. His mass-energy equivalence formula E = mc2, which arises from relativity theory, has been called 'the world's most famous equation'. He received the 1921 Nobel Prize in Physics 'for his services to theoretical physics, and especially for his discovery of the law of the photoelectric effect', a pivotal step in the development of quantum theory. His work is also known for its influence on the philosophy of science. In a 1999 poll of 130 leading physicists worldwide by the British journal Physics World, Einstein was ranked the greatest physicist of all time. His intellectual achievements and originality have made Einstein synonymous with genius.",
    "answer": "Albert Einstein, born on 14 March 1879, was a German-born theoretical physicist, widely held to be one of the greatest and most influential scientists of all time. He received the 1921 Nobel Prize in Physics for his services to theoretical physics. He published 4 papers in 1905. Einstein moved to Switzerland in 1895."
}
Output: {
    "classifications": [
        {
            "statement": "Albert Einstein, born on 14 March 1879, was a German-born theoretical physicist, widely held to be one of the greatest and most influential scientists of all time.",
            "reason": "The date of birth of Einstein is mentioned clearly in the context.",
            "attributed": 1
        },
        {
            "statement": "He received the 1921 Nobel Prize in Physics for his services to theoretical physics.",
            "reason": "The exact sentence is present in the given context.",
            "attributed": 1
        },
        {
            "statement": "He published 4 papers in 1905.",
            "reason": "There is no mention about papers he wrote in the given context.",
            "attributed": 0
        },
        {
            "statement": "Einstein moved to Switzerland in 1895.",
            "reason": "There is no supporting evidence for this in the given context.",
            "attributed": 0
        }
    ]
}

Example 2
Input: {
    "question": "who won 2020 icc world cup?",
    "context": "The 2022 ICC Men's T20 World Cup, held from October 16 to November 13, 2022, in Australia, was the eighth edition of the tournament. Originally scheduled for 2020, it was postponed due to the COVID-19 pandemic. England emerged victorious, defeating Pakistan by five wickets in the final to clinch their second ICC Men's T20 World Cup title.",
    "answer": "England"
}
Output: {
    "classifications": [
        {
            "statement": "England",
            "reason": "The context clarifies that England won the 2022 edition (which was originally scheduled for 2020).",
            "attributed": 1
        }
    ]
}

Example 3
Input: {
    "question": "What is the tallest mountain in the world?",
    "context": "The Andes is the longest continental mountain range in the world, located in South America. It stretches across seven countries and features many of the highest peaks in the Western Hemisphere. The range is known for its diverse ecosystems, including the high-altitude Andean Plateau and the Amazon rainforest.",
    "answer": "Mount Everest."
}
Output: {
    "classifications": [
        {
            "statement": "Mount Everest.",
            "reason": "The provided context discusses the Andes mountain range, which does not include Mount Everest or directly relate to the world's tallest mountain.",
            "attributed": 0
        }
    ]
}
-----------------------------

Now perform the same with the following input
input: {
    "question": "¿Cuántos días de vacaciones puedo transferir al año siguiente?",
    "context": "Política de vacaciones de NimbusSoft: Los días no utilizados pueden transferirse al año siguiente hasta un máximo de 5 días.\nPolítica de reembolso de gastos de NimbusSoft: El límite diario de alimentación en viajes es de 45 USD.",
    "answer": "Hasta un máximo de 5 días."
}
Output: 
```
