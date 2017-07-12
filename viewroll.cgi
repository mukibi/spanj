#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use CGI;
use Spreadsheet::WriteExcel;
require "./conf.pl";
use feature "switch";
 
our($db,$db_user,$db_pwd,$doc_root);
my $con;

my $content = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/viewroll.cgi">View Student Roll</a>
	<hr> 
};

my $update_session = 0;
my %session = ();

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$session{$tuple[0]} = $tuple[1];		
		}
	}
}

my $post_mode = 0;
my %auth_params;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$post_mode++;
	my $str = "";

	while (<STDIN>) {
		$str .= $_;
	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;
	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}

my @classes = ("1", "2", "3", "4");

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

if ($con) {
	my $prep_stmt = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes'");
	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				if ($rslts[0] eq "1-classes") {
					my $classes = $rslts[1];
					@classes = split/,/,$classes;	
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
	}
}

my $feedback = "";

my @today = localtime;
my $current_yr = $today[5] + 1900;

my $start_yr = $current_yr;

my %fields_precedence = ("adm" => 0, "s_name" => 1, "o_names" => 2, "marks_at_adm" => 3, "subjects" => 4, "clubs_societies" => 5, "sports_games" => 6, "responsibilities" => 7, "house_dorm" => 8);
 
POST_MODE: {
if ($post_mode) {
	if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) {
		unless ( $session{"confirm_code"} eq $auth_params{"confirm_code"}  ) {
			$feedback = qq{<p><span style="color: red">Invalid authorization token received. Perhaps you clicked the 'Back' button on your browser before sending this request?</span>};
			$post_mode = 0;
			last POST_MODE;
		}
	}
	else {
		$feedback = qq{<p><span style="color: red">No authorization token received. Do not alter the HTML FORM to complete this transaction.</span>};
		$post_mode = 0;
		last POST_MODE;
	}

	my @fields_selection = ("adm");
	my %classes_selection = ();
	my %invalid_classes = ();
	
	my %classes_hash = ();

	#that old hash-is-lowercase-value-is-rightcase trick 
	foreach (@classes) {
		@classes_hash{lc($_)} = $_;	
	}

	my $num_cols = 2;
	my ($show_name, $show_picture, $show_marks_at_adm, $show_subjects, $show_clubs_societies, $show_games_sports, $show_responsibilities, $show_house_dorm) = (0, 0, 0, 0, 0, 0, 0, 0);

	for my $param (keys %auth_params) {
	
		if ($param =~ /^field_(.+)$/) {	
			my $field_name = $1;
			given ($field_name) {
				when ("name") {
					$show_name++;
					push @fields_selection, ("s_name", "o_names");
					$num_cols++;
				}
				when ("picture") {
					$show_picture++;
					#NB: don't fetch this field
					#incr the $num_cols
					$num_cols++;
				}
				when ("marks_at_adm") {
					$show_marks_at_adm++;
					push @fields_selection, "marks_at_adm";
					$num_cols++;
				}
				when ("subjects") {
					$show_subjects++;
					push @fields_selection, "subjects";
					$num_cols++;
				}
				when ("clubs_societies") {
					$show_clubs_societies++;
					push @fields_selection, "clubs_societies";
					$num_cols++;
				}
				when ("games_sports") {
					$show_games_sports++;
					push @fields_selection, "sports_games";
					$num_cols++;
				}
				when ("responsibilities") {
					$show_responsibilities++;
					push @fields_selection, "responsibilities";
					$num_cols++;
				}
				when ("house_dorm") {
					$show_house_dorm++;
					push @fields_selection, "house_dorm";
					$num_cols++;
				}
			}
		}
		if ($param =~ /^class_(.+)$/) {
			my $class_name = $1;
			$class_name = lc($class_name);		
			#add to valid selection
			if ( exists $classes_hash{$class_name} ) {
				$classes_selection{$classes_hash{$class_name}}++;
				if ( $class_name =~ /(\d+)/ ) {
					my $class_yr = $1;
					$start_yr = $current_yr - ($class_yr - 1);
				}
			}
			#add to invalid selection
			else {
				$invalid_classes{$class_name}++;
			}
		}
	}

	my %pictures = ();

	if ($show_picture) {
		use Image::Magick;
		my $magick = Image::Magick->new;

		opendir(my $mugshots_dir, "${doc_root}/images/mugshots/");
		my @mugshots = readdir($mugshots_dir);

		foreach (@mugshots) {
			if ($_ =~ /^(\d+)\.(?:(?:BMP)|(?:JPG)|(?:JPEG)|(?:PNG))/i) {

				my ($width, $height, $size, $format) = $magick->Ping("${doc_root}/images/mugshots/$_");	
				my $scale = 1;	
				if ($width > 120 or $height > 150) {
					my $width_scale = 120/$width;
					my $height_scale = 150/$height;

					$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
				}

				$pictures{$1} = {"fname" => $_, "scale" => $scale};
			}
		}
		closedir $mugshots_dir;
	}

	#no valid selection
	if (not keys %classes_selection) {
		#with invalid selection
		if (keys %invalid_classes) {
			$feedback = qq{<p><span style="color: red">No valid classes were selected.</span> You must select a class from the list provided. If you cannot find the class you want on the list, ask the administrator to edit the <strong>classes</strong> variable.};
		}
		#with no invalid selection
		else {
			$feedback = qq{<p><span style="color: red">No classes were selected</span>};
		}
			$post_mode = 0;
			last POST_MODE;
	}
	elsif (keys %invalid_classes) {
		$feedback = qq{<p><span style="color: red">Some invalid classes were selected.</span> Spanj will only display the valid classes. You must select a class from the list provided. If you cannot find the class you want on the list, ask the administrator to edit the <strong>classes</strong> variable.</span>};	
	}

	my $spreadsheet_mode = 0;	
	if (exists $auth_params{"download"}) {
		$spreadsheet_mode = 1;
	}

	my %un_seen_classes = %classes_selection;

	my %stud_rolls = ();

	#get student rolls from student_rolls
	if ($con) {
		my $prep_stmt1 = $con->prepare("SELECT table_name,class FROM student_rolls WHERE start_year=?");

		if ($prep_stmt1) {
			my $rc = $prep_stmt1->execute($start_yr);
			if ($rc) {
				while (my @rslts = $prep_stmt1->fetchrow_array()) {

					my $class_then = $rslts[1];
					my $yrs_at_sch = ($current_yr - $start_yr) + 1;
					my $class_now = $class_then;
					$class_now =~ s/\d+/$yrs_at_sch/;
	
					#could have don simple exists
					#but that would not have taken care of the case
					#insensitivity I want to guarantee.
					DEFARGE: for my $class (keys %classes_selection) {
						if ($class =~ /^$class_now$/i) {
							$stud_rolls{$rslts[0]}++;
							delete $un_seen_classes{$class};
							last DEFARGE;
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
		}
	}
	
	if (keys %un_seen_classes) {
		$feedback .= qq{<p><span style="color: red">No data found for the following classes:} . join(", ", keys %un_seen_classes) .qq{</span>} ;
	}

	my %stud_data = ();

	if (keys %stud_rolls) {
		my $fields_selection_str = join(",", sort { $fields_precedence{$a} <=> $fields_precedence{$b} } @fields_selection);
			
		if ($con) {
			for my $roll (keys %stud_rolls) {
				my $prep_stmt2 = $con->prepare("SELECT $fields_selection_str FROM `$roll`");
				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while (my @rslts = $prep_stmt2->fetchrow_array()) {
							#set undef/blank to -
							for(my $i = 0; $i < @rslts; $i++) {
								if (not defined $rslts[$i] or $rslts[$i] =~ /^$/) {
									$rslts[$i] = "-";
								}
							}
							#just realized I hav an interesting
							#problem here:- I don't (really) know how many fields
							#I hav fetched. No problem, though. Lesser men hav had bigger problems.	
							$stud_data{$rslts[0]} = {};
							my $cntr = 0;
							if ($show_name) {
								${$stud_data{$rslts[0]}}{"name"} = $rslts[++$cntr] . " " . $rslts[++$cntr];
							}
							if ($show_marks_at_adm) {
								${$stud_data{$rslts[0]}}{"marks_at_adm"} = $rslts[++$cntr];
							}
							if ($show_subjects) {
								${$stud_data{$rslts[0]}}{"subjects"} = $rslts[++$cntr];
							}
							if ($show_clubs_societies) {
								${$stud_data{$rslts[0]}}{"clubs_societies"} = $rslts[++$cntr] 
							}
							if ($show_games_sports) {
								${$stud_data{$rslts[0]}}{"games_sports"} = $rslts[++$cntr];
							}
							if ($show_responsibilities) {
								${$stud_data{$rslts[0]}}{"responsibilities"} = $rslts[++$cntr];
							}
							if ($show_house_dorm) {
								${$stud_data{$rslts[0]}}{"house_dorm"} = $rslts[++$cntr];
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $roll statement: " . $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
				}
			}
		}
	}

		
	my $class_description = join(",", keys %classes_selection) . "($current_yr)";

	#set up workbook, worksheets & bold format
	my ($workbook,$worksheet,$bold,$default_props,$spreadsheet_name, $row,$col) = (undef,undef,undef,undef,0,0);

	
	#begin spreadsheet 
	if ($spreadsheet_mode) {
		$spreadsheet_name = "$class_description.xls";
		
		$workbook = Spreadsheet::WriteExcel->new("${doc_root}/studentrolls/$spreadsheet_name");
		if (defined $workbook) {

			$bold = $workbook->add_format( ("bold" => 1) );
			$default_props = $workbook->add_format( () );	
			$workbook->set_properties( ("title" => "Student roll for $class_description", "comments" => "lecxEetirW::teehsdaerpS htiw detaerC") );
			$worksheet = $workbook->add_worksheet();
			#assume any less can fit
			#in portrait mode.
			if ($num_cols > 5) {
				$worksheet->set_landscape();
			}
			else {
				$worksheet->set_portrait();
			}
			$worksheet->hide_gridlines(0);
		}
		else {
			print STDERR "Could not create workbook: $!$/";
			$spreadsheet_mode = 0;
		}
	}

	#begin html page
	#did not use else because spreadsheet_mode may
	#have been reset above.
	if (!$spreadsheet_mode) {
		$content .=
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
$feedback
<h2>$class_description</h2>
};

	}
	
	if ($spreadsheet_mode) {
		#header;
		$worksheet->fit_to_pages(1,1);
		my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1, "size" => 14);
		my $merge_format = $workbook->add_format(%merge_props);

		$worksheet->merge_range($row, 0, $row, $num_cols, $class_description, $merge_format);
		$row++;

		$worksheet->write_blank ($row, 0, $bold);
		$worksheet->write_string($row, 1, "Adm. No.", $bold);	

		my $col = 2;	
		if ($show_name) {
			$worksheet->write_string($row, $col++, "Name", $bold);
		}
		if ($show_picture) {
			$worksheet->write_string($row, $col++, "Picture", $bold);
		}
		if ($show_marks_at_adm) {
			$worksheet->write_string($row, $col++, "Marks at Admission", $bold);
		}
		if ($show_subjects) {
			$worksheet->write_string($row, $col++, "Subjects", $bold);
		}
		if ($show_clubs_societies) {
			$worksheet->write_string($row, $col++, "Clubs/Societies", $bold);
		}
		if ($show_games_sports) {
			$worksheet->write_string($row, $col++, "Games/Sports", $bold);
		}
		if ($show_responsibilities) {
			$worksheet->write_string($row, $col++, "Responsibilities", $bold);
		}
		if ($show_house_dorm) {
			$worksheet->write_string($row, $col++, "House/Dorm", $bold);
		}

		$row++;
		$col = 0;

		my $class_cntr = 1;

		for my $adm ( sort {$a <=> $b} keys %stud_data ) {
			#set the row's
			#height if user wants
			#a picture and it's available
			if ($show_picture) {
				if (exists $pictures{$adm}) {
					$worksheet->set_row($row, 150);
				}
			}

			$worksheet->write_string($row, $col++, "$class_cntr.");
			$worksheet->write_number($row, $col++, $adm);
	
			if ($show_name) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"name"});
			}

			if ($show_picture) {
				if (exists $pictures{$adm}) {	
					$worksheet->insert_image($row, $col++, qq!${doc_root}/images/mugshots/${$pictures{$adm}}{"fname"}!, 2, 2, ${$pictures{$adm}}{"scale"}, ${$pictures{$adm}}{"scale"});	
				}
				else {
					$worksheet->write_string($row, $col++, "N/A");
				}
			}
			if ($show_marks_at_adm) {
				if (${$stud_data{$adm}}{"marks_at_adm"} =~ /^\d+$/) {
					$worksheet->write_number($row, $col++, ${$stud_data{$adm}}{"marks_at_adm"});
				}
				else {
					$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"marks_at_adm"});
				}
			}
			if ($show_subjects) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"subjects"});	
			}
			if ($show_clubs_societies) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"clubs_societies"});	
			}
			if ($show_games_sports) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"games_sports"});	
			}
			if ($show_responsibilities) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"responsibilities"});	
			}
			if ($show_house_dorm) {
				$worksheet->write_string($row, $col++, ${$stud_data{$adm}}{"house_dorm"});	
			}

			$class_cntr++;
			$row++;	
			$col = 0;
		}
		$workbook->close();
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /studentrolls/$spreadsheet_name\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
   		my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/studentrolls/$spreadsheet_name">/studentrolls/$spreadsheet_name</a>. If you were not, <a href="/studentrolls/$spreadsheet_name">Click here</a> 
</body>
</html>
};

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		if ($con) {
			$con->disconnect();
		}
		exit 0;
	}
	else { 
		if (keys %stud_data) {
			my $t_head = "<THEAD><TH>&nbsp;<TH>Adm. No.";
			if ($show_name) {
				$t_head .= "<TH>Name";
			}
			if ($show_picture) {
				$t_head .= "<TH>Picture";
			}
			if ($show_marks_at_adm) {
				$t_head .= "<TH>Marks at Admission";
			}
			if ($show_subjects) {
				$t_head .= "<TH>Subjects";
			}
			if ($show_clubs_societies) {
				$t_head .= "<TH>Clubs/Societies";
			}
			if ($show_games_sports) {
				$t_head .= "<TH>Games/Sports";
			}
			if ($show_responsibilities) {
				$t_head .= "<TH>Responsibilities";
			}
			if ($show_house_dorm) {
				$t_head .= "<TH>House/Dorm";
			}

			$t_head .= "</THEAD>";

			$content .= qq{<TABLE border="1" cellpadding="5%">$t_head<TBODY>};
			my $class_cntr = 1;
			for my $adm ( sort {$a <=> $b} keys %stud_data ) {
				$content .= "<TR>";
				$content .= qq{<TD>$class_cntr.<TD>$adm};
				if ($show_name) {
					$content .= qq!<TD>${$stud_data{$adm}}{"name"}!;
				}
				if ($show_picture) {
					if (exists $pictures{$adm}) {
						$content .= qq!<TD><IMG height="150" width="120" src="/images/mugshots/${$pictures{$adm}}{"fname"}" href="/images/mugshots/${$pictures{$adm}}{"fname"}">!;
					}
					else {
						$content .= "<TD>N/A";
					}
				}
				if ($show_marks_at_adm) {
					$content .= qq!<TD>${$stud_data{$adm}}{"marks_at_adm"}!;;
				}
				if ($show_subjects) {
					$content .= qq!<TD>${$stud_data{$adm}}{"subjects"}!;
				}
				if ($show_clubs_societies) {
					$content .= qq!<TD>${$stud_data{$adm}}{"clubs_societies"}!;
				}
				if ($show_games_sports) {
					$content .= qq!<TD>${$stud_data{$adm}}{"games_sports"}!;
				}
				if ($show_responsibilities) {
					$content .= qq!<TD>${$stud_data{$adm}}{"responsibilities"}!;
				}
				if ($show_house_dorm) {
					$content .= qq!<TD>${$stud_data{$adm}}{"house_dorm"}!;
				}
				$class_cntr++;
			}
			$content .= "</TBODY></TABLE></BODY></HTML>";
		}
		#error msg
		else {
			$content .= qq{<em>There are no students to display.</em>. Perhaps there's no data in the rolls selected.</body></html>};
		}
	}
	
}
}

#did not use else
#to allow breaking above
#and executing this block instead
if (not $post_mode) {
	my %grouped_classes;
	my @classes_js_str_bts;
	for my $class (@classes) {
		if ($class =~ /(\d+)/) {
			my $yr = $1;
			push @classes_js_str_bts, qq!{class:"$class", year:"$yr"}!;
			$grouped_classes{$yr} = [] unless (exists $grouped_classes{$yr});
			push @{$grouped_classes{$yr}}, $class;
		}
	}
	my $classes_js_str = '';
	if (@classes_js_str_bts) {
		$classes_js_str = '[' . join (",", @classes_js_str_bts) . ']';
	}

	my $classes_select = "";

	$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold">Class</LABEL>};

	foreach (sort keys %grouped_classes) {
		my @yr_classes = @{$grouped_classes{$_}};

		$classes_select .= "<TD>";
		for (my $i = 0; $i < scalar(@yr_classes); $i++) {
			$classes_select .= qq{<INPUT type="checkbox" name="class_$yr_classes[$i]" id="$yr_classes[$i]" value="$yr_classes[$i]" onclick="dis_activate()"><LABEL for="class_$yr_classes[$i]" id="$yr_classes[$i]_label">$yr_classes[$i]</LABEL>};
			#do not append <BR> to the last class
			if ($i < $#yr_classes) {
				$classes_select .= "<BR>";
			}
		}
	}

	$classes_select .= "</TABLE>";
	my $field_select = 
qq{
<TABLE>
<TR><TD style="font-weight: bold">Include the following fields:
<TR>
<TD>
<UL style="list-style-type: none">
<LI><INPUT type="checkbox" name="field_adm_no" value="adm_no" checked readonly><LABEL style="color: grey" for="field_adm_no">Adm. No.</LABEL>
<LI><INPUT type="checkbox" name="field_name" value="name" checked><LABEL for="field_name">Name</LABEL>
<LI><INPUT type="checkbox" name="field_picture" value="picture"><LABEL for="field_picture">Picture</LABEL>
<LI><INPUT type="checkbox" name="field_marks_at_adm" value="marks_at_adm"><LABEL for="field_marks_at_adm">Marks at Admission</LABEL>
<LI><INPUT type="checkbox" name="field_subjects" value="subjects"><LABEL for="field_subjects">Subjects</LABEL>
<LI><INPUT type="checkbox" name="field_clubs_societies" value="clubs_societies"><LABEL for="field_clubs_societies">Clubs/Societies</LABEL>
<LI><INPUT type="checkbox" name="field_games_sports" value="games_sports"><LABEL for="field_games_sports">Games/Sports</LABEL>
<LI><INPUT type="checkbox" name="field_responsibilities" value="responsibilities"><LABEL for="field_responsibilities">Responsibilities</LABEL>
<LI><INPUT type="checkbox" name="field_house_dorm" value="house_dorm"><LABEL for="field_house_dorm">House/Dorm</LABEL>
</UL>
</TABLE>
};

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;
	$update_session++;

	$content =
		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
<SCRIPT>
	var classes = $classes_js_str;
	function dis_activate() {
		var checked_cnt = 0;
		var active_yr = "";

		for (var i = 0; i < classes.length; i++) {
			var checked = document.getElementById(classes[i].class).checked;
			if (checked) {
				checked_cnt++;
				active_yr = classes[i].year;
			}
		}
		//All unchecked, enable all
		if (checked_cnt == 0) {
			for (var i = 0; i < classes.length; i++) {
				document.getElementById(classes[i].class).disabled = false;
				document.getElementById(classes[i].class + "_label").style.color = "black";
			}
		}
		//Some checked, disable all but the current graduating class
		else {
			for (var i = 0; i < classes.length; i++) {
				if (classes[i].year != active_yr) {
					document.getElementById(classes[i].class).disabled = true;
					document.getElementById(classes[i].class + "_label").style.color = "grey";
				}
			}
		}
		
	}
</SCRIPT>
</head>
<body>
$header
$feedback
<FORM action="/cgi-bin/viewroll.cgi" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
$classes_select
<p>$field_select
<p>

<table>
<tr>
<td><INPUT type="submit" name="view" value="View Roll">
<td><INPUT type="submit" name="download" value="Download Roll">
</table>

</FORM>
</body>
</html>
};
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect();

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}


