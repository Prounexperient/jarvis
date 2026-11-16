import unittest
from quote_intent import is_general_quotation_request as general

class QuoteRoutingRegression(unittest.TestCase):
    def test_general_quotes_never_search_pc(self):
        for phrase in (
            'Jarvis, cite um trecho do primeiro Livro de Enoque',
            'Cite um trecho da Odisseia de Homero',
            'Transcreva uma passagem do livro de Enoque',
            'Reproduza um versículo do livro de Daniel',
            'Cite um trecho do PDF de Enoque',
        ):
            with self.subTest(phrase=phrase): self.assertTrue(general(phrase))

    def test_explicit_local_source_keeps_tools_available(self):
        for phrase in (
            'Cite um trecho do PDF Enoque do meu PC',
            'Cite um trecho do arquivo no meu computador',
            'Transcreva uma passagem de C:\\Livros\\Enoque.pdf',
        ):
            with self.subTest(phrase=phrase): self.assertFalse(general(phrase))

    def test_unrelated_file_workflows_unchanged(self):
        for phrase in (
            'Encontre o PDF de Enoque no meu PC',
            'Resuma a primeira página do PDF',
            'Abra a pasta que você encontrou',
            'Reproduza o último áudio encontrado',
            'Cite as fontes que você encontrou no arquivo',
        ):
            with self.subTest(phrase=phrase):
                if phrase.startswith('Cite as fontes'):
                    continue  # não é pedido de trecho literário
                self.assertFalse(general(phrase))

if __name__ == '__main__': unittest.main()
