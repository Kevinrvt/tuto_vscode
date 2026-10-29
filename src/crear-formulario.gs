function crearFormulario() {
  const form = FormApp.create('Inscripción');
  form.setDescription('Completa tus datos para inscribirte.');
  form.setConfirmationMessage('¡Gracias! Tu inscripción fue registrada.');

  // Público: sin inicio de sesión y sin límite de respuestas por usuario.
  form.setRequireLogin(false);
  form.setLimitOneResponsePerUser(false);
  form.setAcceptingResponses(true);
  if (typeof form.setPublished === 'function') {
    form.setPublished(true);
  }

  form.addTextItem().setTitle('Nombre').setRequired(true);
  form.addTextItem().setTitle('Apellido').setRequired(true);

  const soloNueveDigitos = FormApp.createTextValidation()
    .requireTextMatchesPattern('[0-9]{9}')
    .setHelpText('Ingresa 9 dígitos, sin espacios.')
    .build();
  form.addTextItem()
    .setTitle('Número de celular')
    .setRequired(true)
    .setValidation(soloNueveDigitos);

  form.addListItem()
    .setTitle('Ciclo')
    .setChoiceValues(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    .setRequired(true);

  form.addTextItem().setTitle('Universidad').setRequired(true);

  Logger.log('Enlace público: ' + form.getPublishedUrl());
  Logger.log('Enlace de edición: ' + form.getEditUrl());
}
